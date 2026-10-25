"""OAuth sign-in against a real OAuth-protected MCP server (local; no internet, no models)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.oauth_server import oauth_mcp_server  # noqa: E402
from zyven.connections.oauth import OAuthCoordinator  # noqa: E402
from zyven.connections.probe import probe  # noqa: E402
from zyven.connections.store import ConnectionError_, ConnectionStore  # noqa: E402

REDIRECT = "http://127.0.0.1:8765/oauth/callback"


async def _click_allow(url: str) -> tuple[str, str]:
    """Stand-in for the browser: the user presses Allow and is redirected back with a code and the state."""
    async with httpx.AsyncClient(follow_redirects=False) as c:
        r = await c.get(url)
    assert r.status_code in (302, 307), r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q["code"][0], q["state"][0]


async def _sign_in(store: ConnectionStore, coord: OAuthCoordinator, cid: str) -> None:
    url = await coord.start(cid, REDIRECT)
    assert url and url.startswith("http")
    code, state = await _click_allow(url)
    coord.complete(state, code, None)
    await asyncio.wait_for(coord._tasks[cid], 30)


def test_sign_in_stores_tokens_lists_tools_and_never_leaks_them(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        c = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)
        assert c["signed_in"] is False
        await _sign_in(store, OAuthCoordinator(store), c["id"])
        done = store.get(c["id"])
        assert done["signed_in"] is True and done["error"] is None
        assert {t["name"]: t["needs_approval"] for t in done["tools"]} == {"lookup": False, "send_message": True}
        token = next(iter(provider.access))
        assert token not in json.dumps(store.list()) and token not in (tmp_path / "connections" / "connections.json").read_text()
        assert done["secret_names"] == []  # internal OAuth entries are not even listed by name
        assert provider.registrations == 1  # the client registered itself: no id or secret needed

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_later_calls_reuse_the_token_and_refresh_it_silently(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        provider.ttl = 2  # short-lived access tokens
        cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
        await _sign_in(store, OAuthCoordinator(store), cid)
        assert (await probe(store, cid))["tools"] and provider.refreshes == 0  # stored token, no browser
        await asyncio.sleep(2.6)  # the access token expires; a brand-new provider must notice and refresh
        again = await probe(store, cid)
        assert again["error"] is None and again["tools"] and provider.refreshes == 1  # renewed without the user

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_when_the_sign_in_cannot_be_renewed_the_connection_asks_to_sign_in_again(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
        await _sign_in(store, OAuthCoordinator(store), cid)
        store.update(cid, enabled=True)
        provider.access.clear()
        provider.refresh.clear()  # revoked on the service side: the next call is refused
        dead = await asyncio.wait_for(probe(store, cid), 30)  # must fail fast, never open a browser or hang
        assert dead["tools"] is None and dead["enabled"] is False and "ign" in dead["error"]

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_unknown_or_reused_state_is_refused_and_a_cancel_is_reported(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        coord = OAuthCoordinator(store)
        with pytest.raises(KeyError):
            coord.complete("not-a-real-state", "code", None)
        cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
        url = await coord.start(cid, REDIRECT)
        state = parse_qs(urlparse(url).query)["state"][0]
        coord.complete(state, None, "access_denied")  # the user pressed Cancel
        await asyncio.wait_for(asyncio.gather(coord._tasks[cid], return_exceptions=True), 30)
        assert store.get(cid)["signed_in"] is False and store.get(cid)["error"]
        with pytest.raises(KeyError):
            coord.complete(state, "code", None)  # a state can be used once

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_sign_out_removes_the_tokens_and_turns_the_connection_off(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        coord = OAuthCoordinator(store)
        cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
        await _sign_in(store, coord, cid)
        store.update(cid, enabled=True)
        coord.sign_out(cid)
        out = store.get(cid)
        assert out["signed_in"] is False and out["enabled"] is False and out["tools"] is None
        assert (await probe(store, cid))["error"] == "Sign in first."

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_oauth_connections_take_no_pasted_headers_and_a_secret_needs_its_id(tmp_path):
    store = ConnectionStore(tmp_path)
    with pytest.raises(ConnectionError_, match="no pasted headers"):
        store.add(name="x", kind="http", url="https://mcp.example.com/mcp", oauth=True, secrets={"Authorization": "Bearer x"})
    with pytest.raises(ConnectionError_, match="client id"):
        store.add(name="x", kind="http", url="https://mcp.example.com/mcp", oauth=True, oauth_client_secret="s")
    with pytest.raises(ConnectionError_, match="only applies"):
        store.add(name="x", kind="stdio", command="npx", oauth=True)
    c = store.add(name="Google", kind="http", url="https://mcp.example.com/mcp", oauth=True,
                  oauth_client_id="abc.apps.example.com", oauth_client_secret="shh-secret")
    assert "shh-secret" not in json.dumps(store.list()) and c["secret_names"] == []


def test_the_issuer_from_the_redirect_is_checked_not_thrown_away(tmp_path):
    """Notion advertises authorization_response_iss_parameter_supported and rejects a sign-in whose redirect
    handling drops `iss`. The value must reach the SDK, which compares it with the server's issuer."""
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        coord = OAuthCoordinator(store)
        good = store.add(name="Good issuer", kind="http", url=base + "/mcp", oauth=True)["id"]
        code, state = await _click_allow(await coord.start(good, REDIRECT))
        coord.complete(state, code, None, iss=base)
        await asyncio.wait_for(coord._tasks[good], 30)
        assert store.get(good)["signed_in"] is True and store.get(good)["error"] is None

        bad = store.add(name="Wrong issuer", kind="http", url=base + "/mcp", oauth=True)["id"]
        code, state = await _click_allow(await coord.start(bad, REDIRECT))
        coord.complete(state, code, None, iss="https://evil.example")  # a mix-up attack: the answer came from elsewhere
        await asyncio.wait_for(asyncio.gather(coord._tasks[bad], return_exceptions=True), 30)
        assert store.get(bad)["signed_in"] is False and "iss mismatch" in store.get(bad)["error"]

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_pressing_sign_in_again_replaces_the_old_attempt_without_leaving_an_error(tmp_path):
    store = ConnectionStore(tmp_path)

    async def go(base, provider):
        coord = OAuthCoordinator(store)
        cid = store.add(name="Hosted demo", kind="http", url=base + "/mcp", oauth=True)["id"]
        first = await coord.start(cid, REDIRECT)
        old_state = parse_qs(urlparse(first).query)["state"][0]
        assert coord.active(cid)
        second = await coord.start(cid, REDIRECT)  # the user clicked again: the first attempt is replaced
        await asyncio.sleep(0.2)
        assert store.get(cid)["error"] is None  # the cancelled attempt must not record a failure
        with pytest.raises(KeyError):
            coord.complete(old_state, "code", None)  # a tab from the first attempt is refused, plainly
        code, state = await _click_allow(second)
        coord.complete(state, code, None)
        await asyncio.wait_for(coord._tasks[cid], 30)
        done = store.get(cid)
        assert done["signed_in"] is True and done["error"] is None and not coord.active(cid)

    with oauth_mcp_server() as (base, provider):
        asyncio.run(go(base, provider))


def test_a_service_that_refuses_automatic_registration_gets_a_plain_instruction_not_its_error_page():
    from zyven.connections.oauth import friendly_error

    class OAuthRegistrationError(Exception):  # the MCP client's error, matched by name
        pass

    page = OAuthRegistrationError("Registration failed: 404 <!DOCTYPE html><html><title>There's been a glitch</title>")
    for err in (page, BaseExceptionGroup("unhandled errors in a TaskGroup", [page])):
        msg = friendly_error(err)
        assert "client id and secret" in msg and "<html" not in msg.lower() and "DOCTYPE" not in msg
    assert friendly_error(ValueError("boom")) == "ValueError: boom"
