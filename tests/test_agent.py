"""Offline tests for the self-extending agent's building blocks (no network, no API key, no Docker)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.agent.gap import MissingCapability, Option, gap_check, match_capability  # noqa: E402
from zyven.ai import provider as prov  # noqa: E402
from zyven.ai.provider import ModelProvider  # noqa: E402
from zyven.ai.schemas import CapabilitySpec, ReturnField, ToolParam, ToolSpec  # noqa: E402
from zyven.catalog.catalog import Catalog  # noqa: E402
from zyven.memory.skills import SkillLibrary  # noqa: E402


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)


def fake_model(*payloads: dict) -> ModelProvider:
    """A provider whose replies are the given JSON objects, in order."""
    queue = [json.dumps(p) for p in payloads]

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"choices": [{"message": {"role": "assistant", "content": queue.pop(0)}, "finish_reason": "stop"}]}
        return httpx.Response(200, json=body)

    p = ModelProvider("https://example.invalid/v1", "m", "k")
    p._client = httpx.Client(transport=httpx.MockTransport(handler))
    return p


# ---- skill library ----------------------------------------------------------------------------

def _write_skill(root: Path, name: str, passed: bool) -> None:
    d = root / name
    d.mkdir(parents=True)
    spec = CapabilitySpec(name=name, title=name.title(), summary="does a thing", included_symbols=[], relevant_tests=[],
                          tools=[ToolSpec(name="t", description="d", params=[ToolParam(name="x", type="string", description="x")],
                                          returns=[ReturnField(name="y", type="string", description="y")],
                                          implementation_symbols=[], implementation_notes="", example_args={"x": "1"})])
    (d / "capability.json").write_text(spec.model_dump_json(), encoding="utf-8")
    (d / "server.py").write_text("# server\n", encoding="utf-8")
    (d / "validation-report.json").write_text(json.dumps({"passed": passed, "verified_for": ["policy"] if passed else []}),
                                              encoding="utf-8")
    (d / "provenance.json").write_text(json.dumps({"repository": "https://x/y", "commit": "abc1234def",
                                                   "source_checkout": "/tmp/src"}), encoding="utf-8")


def test_library_lists_only_verified_skills(tmp_path):
    _write_skill(tmp_path, "good_skill", passed=True)
    _write_skill(tmp_path, "bad_skill", passed=False)
    lib = SkillLibrary(tmp_path)
    assert [s.name for s in lib.list()] == ["good_skill"]
    skill = lib.get("good_skill")
    assert skill.source == "https://x/y @ abc1234"
    assert skill.server_spec().env == {"PYTHONPATH": "/tmp/src"}  # wrap mode imports the pinned source
    assert lib.get("bad_skill") is None


def test_library_records_call_health(tmp_path):
    lib = SkillLibrary(tmp_path)
    lib.record_call("s", "t", True, "task")
    lib.record_call("s", "t", False, "task")
    assert lib.health() == {"s": {"ok": 1, "calls": 2}}


# ---- catalog ----------------------------------------------------------------------------------

def test_catalog_curated_entries_replace_and_hidden_ones_disappear(tmp_path):
    (tmp_path / "repos.json").write_text(json.dumps({"repos": [{
        "name": "lib", "url": "https://example.invalid/lib", "commit": "c0ffee", "license": "MIT",
        "curated": [{"name": "good", "title": "Good", "description": "reviewed", "entry_points": ["lib.f"]}],
        "hide": ["weak"],
    }]}), encoding="utf-8")
    runs = tmp_path / "ws/runs/lib"
    runs.mkdir(parents=True)
    scout = {"capabilities": [
        {"name": "weak", "title": "Weak", "description": "x", "entry_points": ["lib.a"], "why_agents_need_it": "x"},
        {"name": "good", "title": "Old good", "description": "x", "entry_points": ["lib.b"], "why_agents_need_it": "x"},
        {"name": "other", "title": "Other", "description": "x", "entry_points": ["lib.c"], "why_agents_need_it": "x"},
    ]}
    (runs / "scout.json").write_text(json.dumps(scout), encoding="utf-8")
    cat = Catalog(tmp_path / "repos.json", tmp_path / "ws")
    caps = cat.capabilities(cat.repos[0])
    assert [c.name for c in caps] == ["good", "other"]
    assert caps[0].entry_points == ["lib.f"]  # the reviewer's boundary wins
    assert [o.id for o in cat.options()] == ["lib:good", "lib:other"]


# ---- gap check and matching -------------------------------------------------------------------

def test_gap_check_keeps_its_answer_consistent():
    p = fake_model({"plan": ["convert the date"], "can_complete_with_current_tools": True,  # contradicts itself
                    "missing_capabilities": [{"description": "convert Hijri dates", "inputs": "date",
                                              "outputs": "date", "why_needed": "exact calendar"}]})
    g = gap_check(p, "What is 1 Ramadan 1447 in the Gregorian calendar?", [])
    assert g.missing_capabilities and g.can_complete_with_current_tools is False


def test_match_rejects_invented_ids():
    need = MissingCapability(description="validate IBAN", inputs="iban", outputs="valid?", why_needed="checksum")
    options = [Option(id="stdnum:iban_validation", title="IBAN", description="validate IBANs")]
    assert match_capability(fake_model({"choice": "stdnum:iban_validation", "confidence": "high", "reason": "fits"}),
                            need, options).choice == "stdnum:iban_validation"
    m = match_capability(fake_model({"choice": "made:up", "confidence": "high", "reason": "?"}), need, options)
    assert m.choice is None and m.confidence == "low"
    assert match_capability(fake_model(), need, []).choice is None  # no options: no model call at all
