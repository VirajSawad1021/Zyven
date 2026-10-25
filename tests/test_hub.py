"""The Zyven hub: tokens per run, connected tools behind approvals, verified skills, and revocation (real HTTP, no model)."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import textwrap
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import Client  # noqa: E402
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client  # noqa: E402

from tests.test_connections import SERVER  # noqa: E402
from zyven.agent.mcp_tools import MCPServerSpec  # noqa: E402
from zyven.connections.store import ConnectionStore  # noqa: E402
from zyven.hub.hub import ZyvenHub  # noqa: E402

SKILL = textwrap.dedent('''
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer("calendar-skill")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def weekday_of(date: str) -> str:
        """Day of the week for an ISO date."""
        import datetime
        return datetime.date.fromisoformat(date).strftime("%A")

    if __name__ == "__main__":
        server.run("stdio")
''')


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def serving(hub: ZyvenHub):
    port = _free_port()
    uv = uvicorn.Server(uvicorn.Config(hub.asgi(), host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=uv.run, daemon=True)
    t.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        uv.should_exit = True
        t.join(10)


def _client(url: str, token: str) -> Client:
    return Client(streamable_http_client(url, http_client=create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})),
                  read_timeout_seconds=60)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_STDIO_CONNECTORS", "1")
    demo, skill = tmp_path / "demo.py", tmp_path / "skill.py"
    demo.write_text(SERVER, encoding="utf-8")
    skill.write_text(SKILL, encoding="utf-8")
    store = ConnectionStore(tmp_path)
    c = store.add(name="Demo notes", kind="stdio", command=sys.executable, args=[str(demo)])
    store.update(c["id"], tools=[], enabled=True)
    off = store.add(name="Switched off", kind="stdio", command=sys.executable, args=[str(demo)])  # never enabled
    asked: list[tuple] = []
    answer = {"yes": True}

    def approve(run_id, kind, summary, detail):
        asked.append((run_id, kind, summary, detail))
        return answer["yes"]

    hub = ZyvenHub(lambda: store, lambda: [MCPServerSpec.python_script("calendar", skill)], approve)
    return hub, asked, answer, off["id"]


def test_requests_without_a_live_token_are_refused(world):
    import httpx

    hub, *_ = world
    with serving(hub) as url:
        assert httpx.post(url, json={}).status_code == 401
        assert httpx.post(url, json={}, headers={"Authorization": "Bearer made-up"}).status_code == 401


def test_a_run_sees_its_connected_tools_and_the_verified_skills_but_not_disabled_connections(world):
    hub, *_ = world
    token = hub.issue("run1")

    async def go(url):
        async with _client(url, token) as client:
            return {t.name for t in (await client.list_tools()).tools}

    with serving(hub) as url:
        names = asyncio.run(go(url))
    assert {"demo_notes__lookup", "demo_notes__send_message", "demo_notes__whoami", "weekday_of"} <= names
    assert not any(n.startswith("switched_off") for n in names)


def test_reads_and_skills_run_freely_and_writes_wait_for_the_users_decision(world):
    hub, asked, answer, _ = world
    token = hub.issue("run1")

    async def go(url):
        async with _client(url, token) as client:
            free = await client.call_tool("demo_notes__lookup", {"q": "x"})
            skill = await client.call_tool("weekday_of", {"date": "2026-10-25"})
            assert asked == []  # reading and verified skills never ask
            allowed = await client.call_tool("demo_notes__send_message", {"text": "hi"})
            answer["yes"] = False
            denied = await client.call_tool("demo_notes__send_message", {"text": "again"})
            return free, skill, allowed, denied

    with serving(hub) as url:
        free, skill, allowed, denied = asyncio.run(go(url))
    assert "found x" in str(free.content) and "Sunday" in str(skill.content)
    assert not allowed.is_error and "sent" in str(allowed.content)
    assert denied.is_error and "Denied" in str(denied.content)
    assert [a[:3] for a in asked] == [("run1", "tool_call", "Demo notes: demo_notes__send_message")] * 2
    assert json.loads(asked[0][3]) == {"text": "hi"} and json.loads(asked[1][3]) == {"text": "again"}


def test_two_runs_are_kept_apart_and_a_revoked_token_stops_working(world):
    import httpx

    hub, asked, _, _ = world
    a, b = hub.issue("runA"), hub.issue("runB")

    async def write(url, token):
        async with _client(url, token) as client:
            await client.call_tool("demo_notes__send_message", {"text": "from " + token[:4]})

    async def go(url):
        await write(url, a)
        await write(url, b)
        await hub.revoke("runA")

    with serving(hub) as url:
        asyncio.run(go(url))
        assert [x[0] for x in asked] == ["runA", "runB"]  # each approval names the run that asked
        assert httpx.post(url, json={}, headers={"Authorization": f"Bearer {a}"}).status_code == 401
        assert httpx.post(url, json={}, headers={"Authorization": f"Bearer {b}"}).status_code != 401
        assert "runA" not in hub._sessions and "runB" in hub._sessions
        asyncio.run(hub.revoke("runB"))
        assert hub._sessions == {}
