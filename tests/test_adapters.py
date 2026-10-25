"""Control center runtime adapters (no Docker, no network, no model calls)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.orchestrator.adapters import RunContext, RuntimeAdapter  # noqa: E402
from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter, parse_stream_line  # noqa: E402
from zyven.orchestrator.control import Control, runtime_info  # noqa: E402
from tests.test_control import FakeBoard  # noqa: E402


class ScriptedAdapter(RuntimeAdapter):
    name, label = "scripted", "Scripted"
    exposes = {"live_output": True}

    def __init__(self, code: int = 0) -> None:
        self.code, self.seen = code, None

    def run(self, ctx: RunContext) -> int:
        self.seen = ctx
        ctx.emit("out", "hello")
        (ctx.cwd / "made.txt").write_text("x", encoding="utf-8")
        return self.code


class Unavailable(RuntimeAdapter):
    name, label = "off", "Off"

    def available(self):
        return False, "switched off for this test"


def _control(tmp_path, *adapters) -> Control:
    c = Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {a.name: a for a in adapters}, autostart=False)
    return c


def test_worker_runs_any_adapter_and_records_output_files_and_status(tmp_path):
    a = ScriptedAdapter()
    c = _control(tmp_path, a)
    rid = c.create(title="t", runtime="scripted", prompt="do it")["id"]
    c._run_worker(rid)
    run = c.get(rid)
    assert run["status"] == "COMPLETED" and run["exit_code"] == 0
    assert run["files"]["added"] == ["made.txt"]
    assert any(e["text"] == "hello" for e in run["log"])
    assert a.seen.run["prompt"] == "do it" and a.seen.cwd == a.seen.workdir


def test_nonzero_exit_marks_the_run_failed(tmp_path):
    c = _control(tmp_path, ScriptedAdapter(code=3))
    rid = c.create(title="", runtime="scripted", prompt="x")["id"]
    c._run_worker(rid)
    assert c.get(rid)["status"] == "FAILED" and c.get(rid)["exit_code"] == 3


def test_unknown_and_unavailable_runtimes_are_rejected(tmp_path):
    c = _control(tmp_path, Unavailable())
    with pytest.raises(ValueError, match="unknown runtime"):
        c.create(title="", runtime="nope", prompt="x")
    with pytest.raises(ValueError, match="switched off"):
        c.create(title="", runtime="off", prompt="x")


def test_runtime_info_lists_the_agent_and_every_adapter(tmp_path):
    info = runtime_info({"off": Unavailable(), "scripted": ScriptedAdapter()})
    assert set(info) == {"zyven", "off", "scripted"}
    assert info["off"]["available"] is False and "switched off" in info["off"]["note"]


def test_claude_adapter_is_off_by_default_and_limits_tools(monkeypatch):
    monkeypatch.delenv("ZYVEN_ENABLE_CLAUDE", raising=False)
    a = ClaudeCodeAdapter()
    ok, why = a.available()
    assert not ok and "ZYVEN_ENABLE_CLAUDE=1" in why and a.open_weight is False
    monkeypatch.setattr("shutil.which", lambda name: "claude")
    cmd = a.command()
    assert cmd[:2] == ["claude", "-p"] and "Bash" not in cmd[cmd.index("--tools") + 1]
    assert "--no-session-persistence" in cmd and "--max-budget-usd" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "user" and cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "make a file" not in cmd  # the prompt goes on stdin


def test_claude_stream_lines_become_events():
    events: list[tuple[str, str]] = []
    emit = lambda k, t: events.append((k, t))  # noqa: E731
    parse_stream_line(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Creating the file."},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "a.txt"}}]}}), emit)
    failed = parse_stream_line(json.dumps({"type": "result", "is_error": False, "result": "Done.",
                                           "total_cost_usd": 0.0123, "usage": {"input_tokens": 10, "output_tokens": 5}}), emit)
    assert not failed
    assert events[0] == ("out", "Creating the file.") and events[1][0] == "tool" and "Write" in events[1][1]
    assert any(k == "info" and "10 in / 5 out" in t and "$0.0123" in t for k, t in events)
    assert parse_stream_line(json.dumps({"type": "result", "is_error": True}), emit) is True
    parse_stream_line("not json", emit)
    assert events[-1] == ("out", "not json")


# --- approvals ---------------------------------------------------------------------------------------

import threading  # noqa: E402
import time  # noqa: E402


class AsksFirst(RuntimeAdapter):
    name, label = "asks", "Asks first"

    def __init__(self) -> None:
        self.acted = None

    def run(self, ctx: RunContext) -> int:
        self.acted = ctx.approve("send_mail", "Send the report to a@example.com", "Subject: Report")
        ctx.emit("out", "sent" if self.acted else "not sent")
        return 0


def _wait_pending(c, rid, tries=100):
    for _ in range(tries):
        pending = c.approvals_for(run=rid, pending_only=True)
        if pending:
            return pending[0]
        time.sleep(0.05)
    raise AssertionError("no approval appeared")


def _run_in_thread(c, rid):
    t = threading.Thread(target=c._run_worker, args=(rid,))
    t.start()
    return t


def test_run_waits_for_approval_then_acts_when_approved(tmp_path):
    a = AsksFirst()
    c = _control(tmp_path, a)
    rid = c.create(title="", runtime="asks", prompt="mail it")["id"]
    t = _run_in_thread(c, rid)
    ap = _wait_pending(c, rid)
    assert c.get(rid)["status"] == "NEEDS_APPROVAL" and ap["kind"] == "send_mail"
    assert a.acted is None  # nothing happened yet
    assert c.decide(ap["id"], True)["status"] == "APPROVED"
    t.join(5)
    assert a.acted is True and c.get(rid)["status"] == "COMPLETED"


def test_denied_approval_means_the_adapter_does_not_act(tmp_path):
    a = AsksFirst()
    c = _control(tmp_path, a)
    rid = c.create(title="", runtime="asks", prompt="mail it")["id"]
    t = _run_in_thread(c, rid)
    c.decide(_wait_pending(c, rid)["id"], False)
    t.join(5)
    assert a.acted is False and any(e["text"] == "not sent" for e in c.get(rid)["log"])


def test_unanswered_approval_expires_as_a_denial(tmp_path):
    c = _control(tmp_path, AsksFirst())
    rid = c.create(title="", runtime="asks", prompt="x")["id"]
    assert c.request_approval(rid, "post", "Post a message", ttl=0.2, poll=0.05) is False
    assert c.approvals_for(run=rid)[0]["status"] == "EXPIRED"


def test_cancel_denies_a_waiting_approval_and_decisions_are_final(tmp_path):
    a = AsksFirst()
    c = _control(tmp_path, a)
    rid = c.create(title="", runtime="asks", prompt="x")["id"]
    t = _run_in_thread(c, rid)
    ap = _wait_pending(c, rid)
    c.cancel(rid)
    t.join(5)
    assert a.acted is False and c.get(rid)["status"] == "CANCELLED"
    with pytest.raises(ValueError, match="already"):
        c.decide(ap["id"], True)
    with pytest.raises(KeyError):
        c.decide("missing", True)
