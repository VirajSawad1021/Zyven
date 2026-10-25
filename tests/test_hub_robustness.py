"""Edge cases found by an independent review (OpenCode) of the hub: hangs, a resurrected session, name clashes, starvation."""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.agent.mcp_tools import ToolBox  # noqa: E402
from zyven.connections.store import ConnectionStore  # noqa: E402
from zyven.hub.hub import HubSession, ZyvenHub  # noqa: E402


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": f"{name} tool", "parameters": {"type": "object", "properties": {}}}}


class FakeSource:
    """Stands in for a connection or skill: has a toolbox with these tools, and a ready() that can be made to misbehave."""

    def __init__(self, names, ready=None, label="fake"):
        self.label, self.error = label, None
        self.toolbox = SimpleNamespace(openai_tools=[_tool(n) for n in names], call=self._call)
        self._ready = ready

    async def _call(self, name, args):
        return True, f"called {name}"

    async def ready(self):
        if self._ready:
            await self._ready()

    async def close(self):
        pass


def _session(tmp_path, *sources) -> HubSession:
    s = HubSession("run1", ConnectionStore(tmp_path), [], lambda *a: False)
    s.sources.extend(sources)
    return s


def test_a_failed_build_is_retried_not_awaited_for_ever(tmp_path):
    async def go():
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("a tool server was too slow to start")

        s = _session(tmp_path, FakeSource(["lookup"], flaky))
        with pytest.raises(TimeoutError):
            await s.tools()
        tools = await asyncio.wait_for(s.tools(), 5)  # used to hang for ever: the build marker was never resolved
        assert [t["function"]["name"] for t in tools] == ["lookup", "zyven_status"]

    asyncio.run(go())


def test_one_caller_giving_up_does_not_poison_the_session_for_the_others(tmp_path):
    async def go():
        async def slow():
            await asyncio.sleep(0.4)

        s = _session(tmp_path, FakeSource(["lookup"], slow))
        first = asyncio.create_task(s.tools())
        await asyncio.sleep(0.05)
        first.cancel()  # the agent disconnected mid-request
        with pytest.raises(asyncio.CancelledError):
            await first
        tools = await asyncio.wait_for(s.tools(), 5)
        assert "lookup" in [t["function"]["name"] for t in tools]

    asyncio.run(go())


def test_a_revoked_run_cannot_be_brought_back_to_life_by_a_late_request(tmp_path):
    async def go():
        hub = ZyvenHub(lambda: ConnectionStore(tmp_path), lambda: [], lambda *a: False)
        hub.issue("run1")
        await hub.revoke("run1")  # the run ended while a tool call was still on its way
        with pytest.raises(PermissionError, match="has ended"):
            await hub._session("run1")
        assert hub._sessions == {}  # no tool servers were started for a dead run

    asyncio.run(go())


def test_the_status_tool_name_is_reserved_listed_once_and_always_answers_itself(tmp_path):
    async def go():
        s = _session(tmp_path, FakeSource(["zyven_status", "weekday_of"]))  # another source tries to use Zyven's name
        names = [t["function"]["name"] for t in await s.tools()]
        assert names.count("zyven_status") == 1 and "weekday_of" in names
        ok, text = await s.call("zyven_status", {})
        assert ok and "called" not in text  # Zyven's own answer, not the other source's tool
        assert await s.call("weekday_of", {}) == (True, "called weekday_of")

    asyncio.run(go())


def test_a_builtin_tool_cannot_replace_a_servers_tool_of_the_same_name():
    async def go():
        tb = ToolBox()
        tb._route["write_file"] = "some-server"  # a connected server already offers this name
        with pytest.raises(ValueError, match="already in use"):
            tb.add_native("write_file", "x", {"type": "object", "properties": {}}, lambda a: "x")

    asyncio.run(go())


def test_many_waiting_approvals_cannot_starve_the_rest_of_the_board(tmp_path):
    async def go():
        release = threading.Event()
        lock = threading.Lock()
        started = []

        def approve(*args):
            with lock:
                started.append(1)
            release.wait(30)  # a person has not clicked yet
            return True

        s = HubSession("run1", ConnectionStore(tmp_path), [], approve)
        gate = s._gate_for("Notion")
        waiting = [asyncio.create_task(gate("create", {"n": i})) for i in range(48)]
        try:
            for _ in range(60):  # every card must be raised promptly, not queued behind a small shared pool
                if len(started) == 48:
                    break
                await asyncio.sleep(0.1)
            assert len(started) == 48, f"only {len(started)} of 48 approval cards were raised"
            # and the shared default pool, which the rest of the board uses, is still free
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "still responsive"), 5) == "still responsive"
        finally:
            release.set()
            assert all(await asyncio.gather(*waiting))

    asyncio.run(go())
