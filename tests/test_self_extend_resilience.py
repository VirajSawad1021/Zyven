"""The agent keeps going when the advisory gap check glitches, and a failure says what is missing."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.agent import self_extend  # noqa: E402
from zyven.agent.gap import CapabilityMatch, GapCheck, MissingCapability  # noqa: E402
from zyven.agent.loop import AgentResult  # noqa: E402
from zyven.ai.provider import ProviderError  # noqa: E402


def _run(monkeypatch, gap, final_text, error=None):
    def fake_gap(provider, task, tools):
        if isinstance(gap, Exception):
            raise gap
        return gap

    async def fake_agent(provider, task, tb, system=None, max_tokens=None):
        return AgentResult(final_text=final_text, error=error)

    monkeypatch.setattr(self_extend, "gap_check", fake_gap)
    monkeypatch.setattr(self_extend, "run_agent", fake_agent)
    monkeypatch.setattr(self_extend, "match_capability", lambda p, need, options: CapabilityMatch(choice=None, confidence="low", reason="nothing fits"))
    events = []
    library = SimpleNamespace(list=lambda: [], root=Path("."))
    catalog = SimpleNamespace(options=lambda: [])

    async def approve(req):
        return False

    return asyncio.run(self_extend.run_self_extending(
        provider=None, task="do a thing", library=library, catalog=catalog, approve=approve,
        on_event=lambda k, d: events.append((k, d)))), events


def test_a_failing_gap_check_does_not_end_the_task(monkeypatch):
    res, events = _run(monkeypatch, ProviderError("structured output invalid after 2 repairs"), "all done")
    assert res.status == "DONE" and res.answer.final_text == "all done"
    note = next(d["detail"] for k, d in events if k == "GAP_CHECK")
    assert "gap check unavailable" in note and "continuing" in note


def test_a_failure_says_what_tool_is_missing(monkeypatch):
    gap = GapCheck(plan=["push it"], can_complete_with_current_tools=False,
                   missing_capabilities=[MissingCapability(description="push code to GitHub", inputs="code", outputs="a repo", why_needed="publish")])
    res, _ = _run(monkeypatch, gap, "")
    assert res.status == "FAILED"
    assert "I have no tool for: push code to GitHub" in res.answer.final_text and "Connections page" in res.answer.final_text


def test_a_provider_error_is_reported_in_the_answer(monkeypatch):
    res, _ = _run(monkeypatch, GapCheck(plan=[], can_complete_with_current_tools=True), "", error="HTTP 429 quota")
    assert res.status == "FAILED" and "HTTP 429 quota" in res.answer.final_text


def test_the_gap_check_does_not_count_tools_that_run_the_agents_own_code():
    from zyven.agent.self_extend import verified_tools

    def tool(name):
        return {"function": {"name": name, "description": "d"}}

    names = ["list_files", "run_command", "run_command_with_network", "hijri__convert", "write_file"]
    assert [t["function"]["name"] for t in verified_tools([tool(n) for n in names])] == ["list_files", "hijri__convert", "write_file"]
