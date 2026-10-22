"""Offline tests for the foundation: provider behaviour, scoring, sandbox result parsing, reference skill.

No network and no API key: model hosts are replaced by an in-process fake HTTP transport.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_eval import _BS_MONTHS, extract_answer, parse_date, score  # noqa: E402
from eval.tasks import Task, generate  # noqa: E402
from zyven.ai import provider as prov  # noqa: E402
from zyven.ai.provider import ModelProvider, ProviderError, is_proprietary, strip_thoughts  # noqa: E402
from zyven.sandbox.runner import SandboxResult, parse_pytest, parse_unittest  # noqa: E402


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)


def fake_host(responses: list[tuple[int, dict | str]], seen: list | None = None) -> httpx.Client:
    """httpx client whose replies come from `responses` in order."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        status, body = queue.pop(0)
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def reply(content: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2}}


def make(responses, **kw) -> ModelProvider:
    p = ModelProvider("https://example.invalid/v1", "gemma-4-26b-a4b-it", "test-key", **kw)
    p._client = fake_host(responses)
    return p


# ---- provider ---------------------------------------------------------------------------------

def test_strip_thoughts_removes_inline_reasoning():
    assert strip_thoughts("<thought>long\nreasoning</thought>ANSWER: 42") == "ANSWER: 42"
    assert strip_thoughts(None) == ""
    # An unpaired tag is dropped without losing the answer around it.
    assert strip_thoughts("Yes, the IBAN is valid.</thought>") == "Yes, the IBAN is valid."


def test_proprietary_detection():
    assert is_proprietary("gemini-3.5-flash")
    assert is_proprietary("openai/gpt-5")
    assert not is_proprietary("gemma-4-26b-a4b-it")
    assert not is_proprietary("google/gemma-4-26b-a4b-it:free")
    assert not is_proprietary("qwen/qwen3-32b")


def test_retries_server_errors_then_succeeds():
    p = make([(500, "Internal error"), (503, "busy"), (200, reply("ok"))])
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.content == "ok" and r.attempts == 3
    assert p.stats.calls == 1 and p.stats.retries == 2


def test_cline_wrapped_response_is_unwrapped():
    p = make([(200, {"success": True, "data": reply("ok")})])
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.content == "ok"
    assert p.stats.prompt_tokens == 3 and p.stats.completion_tokens == 2


def test_seed_and_token_usage_are_exposed():
    seen: list = []
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    p._client = fake_host([(200, reply("ok"))], seen)
    r = p.chat([{"role": "user", "content": "hi"}], seed=123)
    assert seen[0]["seed"] == 123
    assert (r.prompt_tokens, r.completion_tokens) == (3, 2)


def test_unexpected_response_shape_raises_provider_error():
    p = make([(200, {"success": False, "error": "empty response content"})])
    with pytest.raises(ProviderError, match="unexpected response shape"):
        p.chat([{"role": "user", "content": "hi"}])


def test_non_retryable_error_raises_immediately():
    p = make([(400, "bad request"), (200, reply("never reached"))])
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "hi"}])
    assert p.stats.failures == 1


def test_spending_cap_is_not_retried():
    p = make([(429, "Your project has exceeded its monthly spending cap."), (200, reply("never"))])
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "hi"}])


def test_failover_to_backup_host_and_circuit_breaker():
    backup = make([(200, reply("from backup")), (200, reply("again from backup"))])
    primary = make([(500, "down"), (500, "down")], max_retries=2, fallback=backup, cooldown_s=60)
    assert primary.chat([{"role": "user", "content": "1"}]).content == "from backup"
    # while cooling down, the primary is skipped entirely (its queue is empty and would raise if called)
    assert primary.chat([{"role": "user", "content": "2"}]).content == "again from backup"
    assert primary.stats.failovers == 2


class Answer(BaseModel):
    value: int


def test_structured_output_is_validated_and_retried():
    seen: list = []
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    p._client = fake_host([(200, reply('{"value": "not a number"}')), (200, reply('```json\n{"value": 7}\n```'))], seen)
    assert p.generate_structured([{"role": "user", "content": "q"}], Answer).value == 7
    # the retry is a fresh request that describes the validation error, not an echo of the bad output
    assert all(m["role"] != "assistant" for m in seen[1]["messages"])
    assert seen[0]["response_format"]["type"] == "json_schema"


def test_tool_call_metadata_is_dropped_for_other_hosts():
    p = ModelProvider("https://openrouter.ai/api/v1", "m", "k")
    msgs = [{"role": "assistant", "tool_calls": [{"id": "1", "function": {"name": "f"}, "extra_content": {"x": 1}}]}]
    assert "extra_content" not in p._for_host(msgs)[0]["tool_calls"][0]


# ---- evaluation scoring -----------------------------------------------------------------------

def test_task_set_is_deterministic_and_balanced():
    a, b = generate(10), generate(10)
    assert [t.expected for t in a] == [t.expected for t in b]
    assert len(a) == 40 and {t.category for t in a} == {"ad_to_bs", "bs_to_ad", "bs_weekday", "phone_operator"}


@pytest.mark.parametrize("text,expected", [
    ("2057-02-29", "2057-02-29"), ("Jestha 29, 2057 BS", "2057-02-29"), ("29 Poush 2080", "2080-09-29"),
    ("२०८२-०६-१५", "2082-06-15"), ("I am not sure", None),
])
def test_parse_date_accepts_written_and_devanagari_forms(text, expected):
    assert parse_date(text, _BS_MONTHS) == expected


def test_scoring():
    assert extract_answer("reasoning...\nANSWER: **Monday**") == "Monday"
    assert score(Task("x", "bs_weekday", "", "Monday"), "Monday")
    assert score(Task("x", "phone_operator", "", "Ncell"), "Ncell")
    assert not score(Task("x", "phone_operator", "", "Ncell"), "Nepal Telecom or Ncell")  # hedging is wrong


# ---- sandbox result parsing -------------------------------------------------------------------

def test_parse_pytest_summary():
    r = SandboxResult([], 1, "...\n==== 12 passed, 2 failed, 1 error in 0.5s ====\n", "", 1.0)
    rep = parse_pytest(r)
    assert (rep.ran, rep.failures, rep.errors, rep.passed) == (15, 2, 1, False)
    ok = parse_pytest(SandboxResult([], 0, "68 passed in 1.9s\n", "", 1.0))
    assert ok.ran == 68 and ok.passed


def test_parse_unittest_summary():
    r = SandboxResult([], 0, "", "Ran 637 tests in 0.068s\n\nOK\n", 1.0)
    rep = parse_unittest(r)
    assert rep.ran == 637 and rep.passed


def test_zero_tests_is_not_a_pass():
    assert not parse_pytest(SandboxResult([], 0, "no tests ran in 0.01s\n", "", 1.0)).passed


# ---- hand-written reference skill -------------------------------------------------------------

def test_reference_skill_tools():
    sys.path.insert(0, str(ROOT / "toolkit" / "py_nepali_manual"))
    import server  # noqa: PLC0415

    assert server.ad_to_bs("2026-10-12").model_dump()["bs_date"] == "2083-06-26"
    assert server.bs_to_ad("2082-06-15").model_dump() == {"ad_date": "2025-10-01", "weekday": "Wednesday"}
    assert server.parse_nepali_phone("+977-9801234567").operator == "Ncell"
    assert server.parse_nepali_phone("12345").valid is False
