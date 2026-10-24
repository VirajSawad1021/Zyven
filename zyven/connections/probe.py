"""Connect to a stored connection, list its tools, and decide which ones need the user's approval."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from zyven.connections.store import ConnectionStore

PROBE_TIMEOUT_S = 45


def needs_approval(tool: Any) -> bool:
    """A tool runs freely only when its server says it is read-only. Unknown means ask."""
    ann = getattr(tool, "annotations", None)
    return getattr(ann, "read_only_hint", None) is not True


def describe_tools(tools: list[Any]) -> list[dict[str, Any]]:
    return [{"name": t.name, "description": (t.description or "")[:300], "needs_approval": needs_approval(t)}
            for t in tools]


def make_server(conn: dict[str, Any], secrets: dict[str, str], auth: Any = None) -> Any:
    """What `mcp.Client` connects to for this connection: a URL transport with the secrets as headers (or an
    OAuth provider as `auth`), or stdio parameters with the secrets in the environment. Names that start with an
    underscore are Zyven's own bookkeeping (OAuth tokens) and are never sent as headers or environment."""
    secrets = {k: v for k, v in secrets.items() if not k.startswith("_")}
    from mcp.client.stdio import StdioServerParameters
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    if conn["kind"] == "http":
        headers = {k.replace("_", "-"): v for k, v in secrets.items()}  # e.g. Authorization
        return streamable_http_client(conn["url"], http_client=create_mcp_http_client(headers=headers or None, auth=auth))
    return StdioServerParameters(command=conn["command"], args=conn["args"], env={**os.environ, **secrets})


def server_for(store: ConnectionStore, cid: str, conn: dict[str, Any] | None = None) -> Any:
    """The server to connect to for a stored connection, with its secrets and, for OAuth sign-in connections,
    the stored token (refreshed silently; a failed refresh raises SignInNeeded instead of opening a browser)."""
    from zyven.connections.oauth import runtime_provider

    conn = conn or store.get(cid)
    auth = runtime_provider(store, conn) if conn.get("oauth") else None
    return make_server(conn, store.secrets_for(cid), auth=auth)


async def _list_tools(store: ConnectionStore, cid: str, conn: dict[str, Any]) -> list[Any]:
    from mcp import Client

    async with Client(server_for(store, cid, conn), read_timeout_seconds=30) as client:
        return list((await client.list_tools()).tools)


async def probe(store: ConnectionStore, cid: str) -> dict[str, Any]:
    """Try the connection; record the tool list (or the error) on it. Never raises for a failing server."""
    conn = store.get(cid)
    if conn.get("oauth") and not conn.get("signed_in"):
        return store.update(cid, tools=None, enabled=False, error="Sign in first.", checked=time.time())
    try:
        tools = await asyncio.wait_for(_list_tools(store, cid, conn), PROBE_TIMEOUT_S)
        return store.update(cid, tools=describe_tools(tools), error=None, checked=time.time())
    except Exception as e:  # noqa: BLE001 - any transport, auth or launch failure is shown to the user
        inner = e.exceptions[0] if isinstance(e, BaseExceptionGroup) and e.exceptions else e
        msg = f"{type(inner).__name__}: {inner}"
        for v in store.secrets_for(cid).values():  # a server error must not echo a secret back
            msg = msg.replace(v, "***")
        return store.update(cid, tools=None, enabled=False, error=msg[:400], checked=time.time())
