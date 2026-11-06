"""zyven verify on the Connections page: checks on Test, a refused Turn on, and pinned definitions at run time."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from mcp.client.stdio import StdioServerParameters

from zyven.agent.mcp_tools import ToolBox
from zyven.connections.probe import probe
from zyven.connections.runtime import load_enabled
from zyven.connections.store import ConnectionStore
from zyven.mcpverify.checks import DefinitionsChanged, pin_diff, tool_hash

FIX = Path(__file__).parent / "fixtures" / "mcp_servers"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_STDIO_CONNECTORS", "1")
    return ConnectionStore(tmp_path)


def _add(store, script: str, **env):
    return store.add(name=script.title(), kind="stdio", command=sys.executable, args=[str(FIX / f"{script}.py")],
                     secrets=env or None)


def test_pin_diff_reports_changed_and_new_but_not_removed():
    a = {"name": "a", "description": "x"}
    pins = {"a": tool_hash(a), "gone": "123"}
    assert pin_diff([a], pins) == ([], [])
    assert pin_diff([dict(a, description="y"), {"name": "b"}], pins) == (["a"], ["b"])


def test_test_records_the_verdict_and_pins(store):
    c = asyncio.run(probe(store, _add(store, "good")["id"]))
    assert c["verify"]["verdict"] == "PASS" and set(c["pins"]) == {"add"}
    assert [x["name"] for x in c["verify"]["checks"]] == ["handshake", "schemas", "descriptions", "annotations"]


def test_a_poisoned_server_fails_its_test(store):
    c = asyncio.run(probe(store, _add(store, "poisoned")["id"]))
    v = c["verify"]
    assert v["verdict"] == "FAIL"
    desc = next(x for x in v["checks"] if x["name"] == "descriptions")
    assert desc["status"] == "FAIL" and any("send everything to me" in f for f in desc["findings"])


def test_the_board_refuses_to_turn_on_a_failing_server_without_force(store, tmp_path):
    from fastapi.testclient import TestClient

    from zyven.orchestrator.server import create_app
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    with TestClient(create_app(env_path=env, data_dir=tmp_path, board_dir=tmp_path),
                    base_url="http://127.0.0.1") as client:
        cid = client.post("/api/connections", json={"name": "Poisoned", "kind": "stdio", "command": sys.executable,
                                                    "args": [str(FIX / "poisoned.py")]}).json()["id"]
        assert client.post(f"/api/connections/{cid}/test").json()["verify"]["verdict"] == "FAIL"
        refused = client.post(f"/api/connections/{cid}/enabled", json={"enabled": True})
        assert refused.status_code == 409 and "descriptions" in refused.json()["detail"]
        forced = client.post(f"/api/connections/{cid}/enabled", json={"enabled": True, "force": True}).json()
        assert forced["enabled"] is True and forced["verify_override"] is True


def test_a_server_that_changes_after_its_test_is_not_loaded(store, tmp_path):
    state = tmp_path / "starts"
    c = _add(store, "poisoned", RUG_PULL_STATE=str(state))  # its description changes on every start
    asyncio.run(probe(store, c["id"]))
    store.update(c["id"], enabled=True)
    events: list[tuple[str, dict]] = []

    async def run() -> list[str]:
        async with ToolBox() as tb:
            return await load_enabled(tb, store, lambda kind, **kw: events.append((kind, kw)), lambda *_: True)

    assert asyncio.run(run()) == []
    kind, data = events[-1]
    assert kind == "CONNECTION_FAILED" and "differ from the ones you approved" in data["detail"]
    assert "changed: add" in data["detail"] and data["detail"].startswith("Poisoned")


def test_an_unchanged_server_still_loads_with_pins():
    params = StdioServerParameters(command=sys.executable, args=[str(FIX / "good.py")])

    async def run(pins):
        async with ToolBox() as tb:
            try:
                return await tb.add_transport("connection:x", params, pins=pins)
            except DefinitionsChanged as e:  # raised plainly (not in an exception group), the server already closed
                return e

    from zyven.mcpverify import verify_server
    pins = verify_server([sys.executable, str(FIX / "good.py")]).lock
    assert asyncio.run(run(pins)) == ["add"]
    refused = asyncio.run(run({"add": "0000"}))
    assert isinstance(refused, DefinitionsChanged) and refused.changed == ["add"]
