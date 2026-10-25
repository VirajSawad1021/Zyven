"""OAuth sign-in for hosted MCP servers (the "Sign in with ..." flow).

The MCP SDK does the protocol: discovery, dynamic client registration, PKCE, token exchange and refresh.
This module supplies what is specific to Zyven:

  * token and client storage in the connection's local secrets file (never returned by the API),
  * the redirect and callback for the browser step, with the OAuth `state` checked against the flow we started,
  * a non-interactive provider for runtime, which refreshes tokens silently and never opens a browser:
    if a refresh fails the connection reports "sign in again" instead of hanging an agent task.

A service that does not register apps by itself (Google, for example) needs the user's own OAuth client id,
given when adding the connection.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from zyven.connections.store import ConnectionStore

SIGNIN_TIMEOUT_S = 300
FALLBACK_REDIRECT = "http://127.0.0.1/oauth/callback"


class SignInNeeded(Exception):
    """The stored sign-in is missing or expired and cannot be renewed silently."""


class StoreTokenStorage:
    """The SDK's TokenStorage protocol, backed by one connection's entries in the local secrets file."""

    def __init__(self, store: ConnectionStore, cid: str, redirect_uri: str) -> None:
        self.store, self.cid, self.redirect_uri = store, cid, redirect_uri

    async def get_tokens(self) -> OAuthToken | None:
        raw = self.store.secret(self.cid, "_oauth_tokens")
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.store.set_secret(self.cid, "_oauth_tokens", tokens.model_dump_json())
        if tokens.expires_in:  # keep the absolute time: a later process must know whether the token has expired
            self.store.set_secret(self.cid, "_oauth_expires_at", str(time.time() + tokens.expires_in))
        else:
            self.store.delete_secret(self.cid, "_oauth_expires_at")

    def expires_at(self) -> float | None:
        raw = self.store.secret(self.cid, "_oauth_expires_at")
        return float(raw) if raw else None

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        reg = self.store.secret(self.cid, "_oauth_registration")  # what the service gave us when we registered
        if reg:
            return OAuthClientInformationFull.model_validate_json(reg)
        given = self.store.secret(self.cid, "_oauth_client")  # a client id/secret the user registered themselves
        if given:
            c = json.loads(given)
            return OAuthClientInformationFull(
                client_id=c["client_id"], client_secret=c.get("client_secret"), redirect_uris=[self.redirect_uri],
                token_endpoint_auth_method="client_secret_post" if c.get("client_secret") else "none",
                grant_types=["authorization_code", "refresh_token"], response_types=["code"])
        return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.store.set_secret(self.cid, "_oauth_registration", client_info.model_dump_json())


class _Provider(OAuthClientProvider):
    """The SDK starts every new provider with no expiry for the stored token, so a token that expired hours ago
    would be sent, rejected with a 401, and force a full sign-in. Restoring the saved expiry makes it refresh
    silently first."""

    async def _initialize(self) -> None:
        await super()._initialize()
        storage = self.context.storage
        if isinstance(storage, StoreTokenStorage) and self.context.current_tokens:
            self.context.token_expiry_time = storage.expires_at()


def _metadata(redirect_uri: str) -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Zyven", redirect_uris=[redirect_uri], grant_types=["authorization_code", "refresh_token"],
        response_types=["code"], token_endpoint_auth_method="none")  # a public client: PKCE, no secret to keep


def runtime_provider(store: ConnectionStore, conn: dict[str, Any]) -> OAuthClientProvider:
    """Uses (and refreshes) the stored token; never opens a browser."""
    async def no_browser(url: str) -> None:
        raise SignInNeeded(f"{conn['name']}: the sign-in expired. Sign in again on the Connections page.")

    async def no_callback() -> AuthorizationCodeResult:
        raise SignInNeeded(f"{conn['name']}: the sign-in expired. Sign in again on the Connections page.")

    reg = store.secret(conn["id"], "_oauth_registration")
    redirect = (json.loads(reg).get("redirect_uris") or [FALLBACK_REDIRECT])[0] if reg else FALLBACK_REDIRECT
    return _Provider(conn["url"], _metadata(redirect), StoreTokenStorage(store, conn["id"], redirect),
                               redirect_handler=no_browser, callback_handler=no_callback)


@dataclass
class _Flow:
    state: str
    code: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())


class OAuthCoordinator:
    """Runs one sign-in at a time per connection and connects the browser's redirect back to it."""

    def __init__(self, store: ConnectionStore) -> None:
        self.store = store
        self._flows: dict[str, _Flow] = {}  # state -> flow
        self._tasks: dict[str, asyncio.Task] = {}  # connection id -> running sign-in

    async def start(self, cid: str, redirect_uri: str) -> str | None:
        """Begin signing in. Returns the page to open in the browser, or None if no sign-in was needed."""
        from zyven.connections.probe import describe_tools, make_server

        conn = self.store.get(cid)
        if not conn.get("oauth"):
            raise ValueError("this connection does not use OAuth sign-in")
        old = self._tasks.pop(cid, None)
        if old:
            old.cancel()
        loop = asyncio.get_running_loop()
        url_ready: asyncio.Future = loop.create_future()
        flow: dict[str, _Flow] = {}

        async def redirect(url: str) -> None:
            state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
            flow["f"] = self._flows[state] = _Flow(state)
            if not url_ready.done():
                url_ready.set_result(url)

        async def callback() -> AuthorizationCodeResult:
            f = flow["f"]
            try:
                return await asyncio.wait_for(f.code, SIGNIN_TIMEOUT_S)
            finally:
                self._flows.pop(f.state, None)

        async def run() -> None:
            from mcp import Client

            me = asyncio.current_task()

            provider = _Provider(conn["url"], _metadata(redirect_uri),
                                           StoreTokenStorage(self.store, cid, redirect_uri),
                                           redirect_handler=redirect, callback_handler=callback)
            try:
                async with Client(make_server(conn, {}, auth=provider), read_timeout_seconds=30) as client:
                    tools = list((await client.list_tools()).tools)
                self.store.update(cid, tools=describe_tools(tools), error=None, checked=time.time())
            except asyncio.CancelledError:
                raise  # replaced by a newer attempt or signed out: not an error, and it must not overwrite one
            except BaseException as e:  # noqa: BLE001 - shown to the user; also unblocks start()
                if self._tasks.get(cid) is me:  # only the current attempt may record a failure
                    self.store.update(cid, error=_message(e), checked=time.time())
                if not url_ready.done():
                    url_ready.set_exception(RuntimeError(_message(e)))
            finally:
                if not url_ready.done():
                    url_ready.set_result(None)  # signed in already: no browser step was needed

        self._tasks[cid] = asyncio.create_task(run())
        return await asyncio.wait_for(url_ready, 60)

    def active(self, cid: str) -> bool:
        """Is a sign-in for this connection still waiting for the user (or for the service)?"""
        task = self._tasks.get(cid)
        return bool(task and not task.done())

    def complete(self, state: str, code: str | None, error: str | None, iss: str | None = None) -> None:
        """Called by the callback page. Unknown `state` values are refused: this is the CSRF check. `iss` is the
        authorization server's own address (RFC 9207); services such as Notion require it to be checked, so it must
        be passed on to the SDK exactly as received."""
        flow = self._flows.get(state)
        if flow is None or flow.code.done():
            raise KeyError("unknown or already used sign-in")
        if error or not code:
            flow.code.set_exception(SignInNeeded(error or "the service did not return a code"))
        else:
            flow.code.set_result(AuthorizationCodeResult(code=code, state=state, iss=iss))

    def sign_out(self, cid: str) -> None:
        task = self._tasks.pop(cid, None)
        if task:
            task.cancel()
        for key in ("_oauth_tokens", "_oauth_registration", "_oauth_expires_at"):
            self.store.delete_secret(cid, key)
        self.store.update(cid, enabled=False, tools=None, error=None)


def leaf_error(e: BaseException) -> BaseException:
    """The first real error inside nested ExceptionGroups (the MCP client raises 'unhandled errors in a TaskGroup')."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def expire_sign_in(store: ConnectionStore, cid: str) -> str:
    """The service no longer accepts the stored login and it cannot be renewed silently: forget it, so the connection
    shows 'Not signed in' with a Sign in button instead of failing in the dark. Returns the message for the user."""
    for key in ("_oauth_tokens", "_oauth_expires_at"):
        store.delete_secret(cid, key)
    name = store.get(cid)["name"]
    msg = f"{name}: the sign-in expired. Sign in again on the Connections page."
    store.update(cid, enabled=False, tools=None, error=msg)
    return msg


def _message(e: BaseException) -> str:
    inner = e.exceptions[0] if isinstance(e, BaseExceptionGroup) and e.exceptions else e
    return f"{type(inner).__name__}: {inner}"[:400]
