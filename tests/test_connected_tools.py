"""Connected tools reach the agent's toolbox; anything that is not read-only waits for a yes (no network, no models)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_connections import SERVER  # noqa: E402
from zyven.agent.mcp_tools import ToolBox  # noqa: E402
from zyven.connections.probe import make_server  # noqa: E402
from zyven.connections.runtime import load_enabled, make_gate, tool_prefix  # noqa: E402
from zyven.connections.store import ConnectionStore  # noqa: E402


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_STDIO_CONNECTORS", "1")
    script = tmp_path / "demo_server.py"
    script.write_text(SERVER, encoding="utf-8")
    store = ConnectionStore(tmp_path)
    c = store.add(name="Demo notes", kind="stdio", command=sys.executable, args=[str(script)])
    store.update(c["id"], tools=[], enabled=True)
    return store, c["id"]


def test_prefixes_keep_names_apart_and_valid():
    taken: set[str] = set()
    a = tool_prefix("Demo notes!", taken)
    taken.add(a)
    b = tool_prefix("Demo notes", taken)
    assert a == "demo_notes__" and b == "demo_notes2__"


def test_read_only_tools_run_freely_and_the_rest_ask_first(demo):
    store, cid = demo
    asked: list[tuple[str, dict]] = []

    async def gate(tool, args):
        asked.append((tool, args))
        return True

    async def go():
        async with ToolBox() as tb:
            names = await tb.add_transport("demo", make_server(store.get(cid), {}), prefix="demo__", gate=gate)
            assert set(names) == {"demo__lookup", "demo__send_message", "demo__whoami"}
            ok1, out1 = await tb.call("demo__lookup", {"q": "x"})
            assert ok1 and "found x" in out1 and asked == []  # read-only: no question
            ok2, out2 = await tb.call("demo__send_message", {"text": "hi"})
            assert ok2 and "sent" in out2 and asked == [("demo__send_message", {"text": "hi"})]

    asyncio.run(go())


def test_a_denied_call_never_reaches_the_server(demo):
    store, cid = demo

    async def deny(tool, args):
        return False

    async def go():
        async with ToolBox() as tb:
            await tb.add_transport("demo", make_server(store.get(cid), {}), prefix="demo__", gate=deny)
            ok, out = await tb.call("demo__send_message", {"text": "hi"})
            assert ok is False and out.startswith("Denied")

    asyncio.run(go())


def test_without_a_gate_nothing_is_blocked_for_trusted_local_skills(demo):
    store, cid = demo

    async def go():
        async with ToolBox() as tb:
            await tb.add_transport("demo", make_server(store.get(cid), {}))
            ok, out = await tb.call("send_message", {"text": "hi"})
            assert ok and "sent" in out

    asyncio.run(go())


def test_load_enabled_skips_disabled_and_broken_connections_and_asks_through_the_user(demo, tmp_path):
    store, cid = demo
    off = store.add(name="Off one", kind="stdio", command=sys.executable, args=["-c", "pass"])  # never enabled
    broken = store.add(name="Broken", kind="stdio", command=sys.executable, args=["-c", "import sys; sys.exit(3)"])
    store.update(broken["id"], tools=[], enabled=True)
    events: list[tuple[str, dict]] = []
    questions: list = []

    async def ask(req):
        questions.append(req)
        return False

    async def go():
        async with ToolBox() as tb:
            loaded = await load_enabled(tb, store, lambda k, **d: events.append((k, d)), ask)
            assert sorted(loaded) == ["demo_notes__lookup", "demo_notes__send_message", "demo_notes__whoami"]
            ok, out = await tb.call("demo_notes__send_message", {"text": "hi"})
            assert not ok and "Denied" in out

    asyncio.run(go())
    kinds = [k for k, _ in events]
    assert "CONNECTION_LOADED" in kinds and "CONNECTION_FAILED" in kinds
    assert off["id"] not in str(events)
    req = questions[0]
    assert (req.connection, req.tool) == ("Demo notes", "demo_notes__send_message")
    asked_event = next(d for k, d in events if k == "NEEDS_APPROVAL")
    assert asked_event["request"]["kind"] == "tool_call" and asked_event["request"]["arguments"] == {"text": "hi"}
    assert ("RESUMED", {"detail": "denied Demo notes: demo_notes__send_message"}) in events


def test_gate_emits_the_card_event_then_the_decision():
    seen: list[tuple[str, dict]] = []

    async def ask(req):
        return True

    gate = make_gate("GitHub", lambda k, **d: seen.append((k, d)), ask)
    assert asyncio.run(gate("github__create_issue", {"title": "t"})) is True
    assert [k for k, _ in seen] == ["NEEDS_APPROVAL", "RESUMED"] and seen[1][1]["detail"].startswith("approved")
