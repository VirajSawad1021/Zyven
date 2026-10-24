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


def make_server(conn: dict[str, Any], secrets: dict[str, str]) -> Any:
    """What `mcp.Client` connects to for this connection: a URL transport with the secrets as headers, or stdio
    parameters with the secrets in the environment."""
    from mcp.client.stdio import StdioServerParameters
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    if conn["kind"] == "http":
        headers = {k.replace("_", "-"): v for k, v in secrets.items()}  # e.g. Authorization
        return streamable_http_client(conn["url"], http_client=create_mcp_http_client(headers=headers or None))
    return StdioServerParameters(command=conn["command"], args=conn["args"], env={**os.environ, **secrets})


async def _list_tools(conn: dict[str, Any], secrets: dict[str, str]) -> list[Any]:
    from mcp import Client

    async with Client(make_server(conn, secrets), read_timeout_seconds=30) as client:
        return list((await client.list_tools()).tools)


async def probe(store: ConnectionStore, cid: str) -> dict[str, Any]:
    """Try the connection; record the tool list (or the error) on it. Never raises for a failing server."""
    conn = store.get(cid)
    try:
        tools = await asyncio.wait_for(_list_tools(conn, store.secrets_for(cid)), PROBE_TIMEOUT_S)
        return store.update(cid, tools=describe_tools(tools), error=None, checked=time.time())
    except Exception as e:  # noqa: BLE001 - any transport, auth or launch failure is shown to the user
        msg = f"{type(e).__name__}: {e}"
        for v in store.secrets_for(cid).values():  # a server error must not echo a secret back
            msg = msg.replace(v, "***")
        return store.update(cid, tools=None, enabled=False, error=msg[:400], checked=time.time())
