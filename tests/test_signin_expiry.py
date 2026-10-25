"""An expired sign-in must say so: in the Test result, in the hub, and for the Zyven agent (real OAuth server)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.oauth_server import oauth_mcp_server  # noqa: E402
from tests.test_oauth import _sign_in  # noqa: E402
from zyven.agent.mcp_tools import ToolBox  # noqa: E402
from zyven.connections.oauth import OAuthCoordinator  # noqa: E402
from zyven.connections.probe import probe  # noqa: E402
from zyven.connections.runtime import load_enabled  # noqa: E402
from zyven.connections.store import ConnectionStore  # noqa: E402
from zyven.hub.hub import HubSession  # noqa: E402


async def _signed_in_then_revoked(store, base, provider) -> str:
    cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
    await _sign_in(store, OAuthCoordinator(store), cid)
    store.update(cid, enabled=True)
    assert store.get(cid)["signed_in"] is True
    provider.access.clear()
    provider.refresh.clear()  # the service no longer accepts the login and it cannot be renewed
    return cid


def _expired(store, cid) -> bool:
    c = store.get(cid)
    return c["signed_in"] is False and c["enabled"] is False and "sign-in expired" in c["error"] and "ExceptionGroup" not in c["error"]


def test_the_test_button_reports_an_expired_sign_in_in_plain_words_and_forgets_the_login(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        cid = await _signed_in_then_revoked(store, base, provider)
        done = await asyncio.wait_for(probe(store, cid), 40)
        assert _expired(store, cid) and done["error"] == store.get(cid)["error"]

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_the_hub_tells_the_run_and_the_agent_what_is_missing(tmp_path):
    store = ConnectionStore(tmp_path)
    told: list[tuple[str, str]] = []

    async def go(base, provider):
        cid = await _signed_in_then_revoked(store, base, provider)
        session = HubSession("run1", store, [], lambda *a: False, lambda run_id, text: told.append((run_id, text)))
        tools = await asyncio.wait_for(session.tools(), 60)
        assert [t["function"]["name"] for t in tools] == ["zyven_status"]  # nothing else to offer, but the agent can ask why
        ok, text = await session.call("zyven_status", {})
        assert ok and "Hosted demo" in text and "sign-in expired" in text and "Sign in again" in text
        assert _expired(store, cid)
        await session.close()

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))
    assert told and told[0][0] == "run1" and "Zyven hub: Hosted demo unavailable" in told[0][1] and "sign-in expired" in told[0][1]


def test_the_zyven_agent_gets_the_same_plain_message(tmp_path):
    store = ConnectionStore(tmp_path)
    events: list[tuple[str, str]] = []

    async def go(base, provider):
        cid = await _signed_in_then_revoked(store, base, provider)
        async with ToolBox() as tb:
            loaded = await asyncio.wait_for(load_enabled(tb, store, lambda k, **d: events.append((k, d["detail"])), None), 60)
        assert loaded == [] and _expired(store, cid)

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))
    assert events and events[0][0] == "CONNECTION_FAILED" and "sign-in expired" in events[0][1]
