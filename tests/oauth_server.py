"""A real OAuth-protected MCP server for tests: dynamic client registration, PKCE, tokens that can be revoked.

The "authorize" step approves immediately (no login page), which stands in for the user clicking Allow.
"""

from __future__ import annotations

import secrets
import socket
import threading
import time
from contextlib import contextmanager

import uvicorn
from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, OAuthAuthorizationServerProvider, RefreshToken,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.types import ToolAnnotations


class DemoProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self) -> None:
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.codes: dict[str, AuthorizationCode] = {}
        self.access: dict[str, AccessToken] = {}
        self.refresh: dict[str, RefreshToken] = {}
        self.refreshes = 0
        self.ttl = 3600  # seconds an access token lives
        self.registrations = 0
        self.anonymous_listing = False

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        self.registrations += 1
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(16)
        self.codes[code] = AuthorizationCode(
            code=code, scopes=params.scopes or ["read"], expires_at=time.time() + 300, client_id=client.client_id,
            code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly, resource=params.resource)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client, authorization_code):
        return self.codes.get(authorization_code)

    def _issue(self, client_id: str, scopes: list[str]) -> OAuthToken:
        at, rt = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self.access[at] = AccessToken(token=at, client_id=client_id, scopes=scopes, expires_at=int(time.time()) + int(self.ttl))
        self.refresh[rt] = RefreshToken(token=rt, client_id=client_id, scopes=scopes)
        return OAuthToken(access_token=at, token_type="Bearer", expires_in=int(self.ttl), scope=" ".join(scopes), refresh_token=rt)

    async def exchange_authorization_code(self, client, authorization_code):
        self.codes.pop(authorization_code.code, None)
        return self._issue(client.client_id, authorization_code.scopes)

    async def load_refresh_token(self, client, refresh_token):
        return self.refresh.get(refresh_token)

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        self.refreshes += 1
        self.refresh.pop(refresh_token.token, None)
        return self._issue(client.client_id, scopes or refresh_token.scopes)

    async def load_access_token(self, token):
        if token == ANONYMOUS and self.anonymous_listing:
            return AccessToken(token=token, client_id="anonymous", scopes=["read"], expires_at=None)
        return self.access.get(token)

    async def revoke_token(self, token):
        self.access.pop(getattr(token, "token", ""), None)
        self.refresh.pop(getattr(token, "token", ""), None)


ANONYMOUS = "anonymous-listing"  # only ever added by the wrapper below, never handed out
LISTING = {"server/discover", "initialize", "tools/list"}


def _anonymous_listing(app):
    """Like Google's hosted Gmail and Docs servers: starting a session and listing tools need no token; calling a
    tool does (401). A request without a token whose JSON-RPC method only lists is let through as anonymous."""
    import json as _json

    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or any(k == b"authorization" for k, _ in scope["headers"]):
            return await app(scope, receive, send)
        body, more = b"", True
        while more:
            msg = await receive()
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
        try:
            method = _json.loads(body or b"{}").get("method", "")
        except ValueError:
            method = ""
        if scope["method"] in ("GET", "DELETE") or method in LISTING or method.startswith("notifications/"):
            scope = {**scope, "headers": [*scope["headers"], (b"authorization", f"Bearer {ANONYMOUS}".encode())]}
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await app(scope, replay, send)

    return wrapped


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def oauth_mcp_server(anonymous_listing: bool = False):
    """Yields (base_url, provider) for a running OAuth-protected MCP server; the MCP endpoint is {base}/mcp.
    With anonymous_listing, tools can be listed without a token and only calls need one (see _anonymous_listing)."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    provider = DemoProvider()
    provider.anonymous_listing = anonymous_listing
    server = MCPServer(
        "oauth-demo", auth_server_provider=provider,
        auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp", required_scopes=["read"],
                          client_registration_options=ClientRegistrationOptions(
                              enabled=True, valid_scopes=["read"], default_scopes=["read"]),
                          validate_token_resource=False))

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def lookup(q: str) -> str:
        """Look something up."""
        return "found " + q

    @server.tool()
    def send_message(text: str) -> str:
        """Send a message."""
        return "sent"

    app = server.streamable_http_app()
    if anonymous_listing:
        app = _anonymous_listing(app)
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    try:
        yield base, provider
    finally:
        uv.should_exit = True
        thread.join(5)
