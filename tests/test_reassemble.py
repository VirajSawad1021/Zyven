"""`zyven reassemble`: rebuild a skill with the current harness; rerun the gates; restore the old server on failure."""

from __future__ import annotations

import json
from pathlib import Path

from zyven.ai.schemas import AdapterCode, CapabilitySpec, ReturnField, ToolImpl, ToolParam, ToolSpec
from zyven.compiler import reassemble as ra
from zyven.compiler.build import assemble
from zyven.compiler.verify import Gate, VerificationReport


def _skill(root: Path, old_server: str | None = None) -> Path:
    tool = ToolSpec(name="double", description="Double a number.",
                    params=[ToolParam(name="n", type="integer", description="the number")],
                    returns=[ReturnField(name="value", type="integer", description="2n")],
                    implementation_symbols=[], implementation_notes="", example_args={"n": 2})
    spec = CapabilitySpec(name="calc", title="Calc", summary="s", tools=[tool], included_symbols=[], relevant_tests=[])
    code = AdapterCode(tools=[ToolImpl(tool="double", imports=[], body="return {'value': n * 2}")])
    prov = {"repository": "r", "commit": "c", "license": "MIT", "generator": "zyven 0.0.1", "model": "m",
            "source_checkout": str(root / "repo"), "source_root": "."}
    d = root / "lib" / "calc"
    d.mkdir(parents=True)
    (d / "capability.json").write_text(spec.model_dump_json(), encoding="utf-8")
    (d / "adapter-code.json").write_text(code.model_dump_json(), encoding="utf-8")
    (d / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")
    (d / "server.py").write_text(old_server if old_server is not None else assemble(spec, code, prov), encoding="utf-8")
    return d


def _report(passed: bool) -> VerificationReport:
    gates = [Gate(n, passed or n != "differential", "x") for n in
             ("policy", "import", "upstream_tests", "input_robustness", "mcp_smoke", "differential")]
    return VerificationReport(gates, {} if passed else {"double": "mismatch"})


def test_a_current_skill_is_left_alone(tmp_path):
    d = _skill(tmp_path)
    assert ra.reassemble_one(d).status == "up to date"


def test_an_old_skill_is_rebuilt_and_reverified(tmp_path, monkeypatch):
    d = _skill(tmp_path, old_server="# server.py from an older Zyven\n")
    calls = []
    monkeypatch.setattr(ra, "_verify", lambda *a: (calls.append(a) or _report(True), None))
    r = ra.reassemble_one(d)
    assert r.status == "reassembled" and calls
    text = (d / "server.py").read_text(encoding="utf-8")
    assert "read_only_hint=True" in text and 'Field(description="the number")' in text  # today's harness
    prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
    assert prov["reassembled"][-1]["gates_rerun"] is True
    assert not (d / "server.py.before-reassemble").exists()


def test_failed_gates_restore_the_old_server(tmp_path, monkeypatch):
    old = "# server.py from an older Zyven\n"
    d = _skill(tmp_path, old_server=old)
    monkeypatch.setattr(ra, "_verify", lambda *a: (_report(False), None))
    r = ra.reassemble_one(d)
    assert r.status.startswith("kept") and "differential" in r.detail
    assert (d / "server.py").read_text(encoding="utf-8") == old
    assert "reassembled" not in json.loads((d / "provenance.json").read_text(encoding="utf-8"))


def test_a_crash_while_verifying_keeps_the_old_server(tmp_path, monkeypatch):
    old = "# old\n"
    d = _skill(tmp_path, old_server=old)

    def crash(*a):
        raise ValueError("72 validation errors")

    monkeypatch.setattr(ra, "_verify", crash)
    r = ra.reassemble_one(d)
    assert r.status.startswith("kept") and "ValueError" in r.detail
    assert (d / "server.py").read_text(encoding="utf-8") == old


def test_saved_cases_with_typed_arguments_load(tmp_path, monkeypatch):
    d = _skill(tmp_path, old_server="# old\n")
    (tmp_path / "repo").mkdir()
    (d / "diff_tests.json").write_text(json.dumps({"cases": [{
        "tool": "double", "args": {"n": 2, "edges": [["A", "B", 5]]}, "field": "value",
        "reference_imports": [], "reference_expr": "{n} * 2"}]}), encoding="utf-8")
    seen = {}

    def fake_verify(skill_dir, spec, repo, roots, diff_tests=None, **kw):
        seen["cases"] = diff_tests.cases
        return _report(True)

    monkeypatch.setattr("zyven.compiler.verify.verify", fake_verify)
    assert ra.reassemble_one(d).status == "reassembled"
    assert seen["cases"][0].args["edges"] == [["A", "B", 5]]


def test_a_missing_source_checkout_keeps_the_old_server(tmp_path):
    old = "# old\n"
    d = _skill(tmp_path, old_server=old)  # tmp_path/repo does not exist
    r = ra.reassemble_one(d)
    assert r.status.startswith("kept") and "missing" in r.detail
    assert (d / "server.py").read_text(encoding="utf-8") == old


def test_dry_run_changes_nothing_and_a_library_is_walked(tmp_path):
    d = _skill(tmp_path, old_server="# old\n")
    (tmp_path / "lib" / "not-a-skill").mkdir()
    results = ra.reassemble([tmp_path / "lib"], dry_run=True)
    assert [(r.skill, r.status) for r in results] == [("calc", "would reassemble")]
    assert (d / "server.py").read_text(encoding="utf-8") == "# old\n"
