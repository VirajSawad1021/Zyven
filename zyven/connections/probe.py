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


async def _list_tools(store: ConnectionStore, cid: str, conn: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    from mcp import Client

    async with Client(server_for(store, cid, conn), read_timeout_seconds=30) as client:
        info = client.server_info
        meta = {"name": getattr(info, "name", ""), "version": getattr(info, "version", ""),
                "protocol": str(client.protocol_version or ""), "instructions": client.instructions or ""}
        return list((await client.list_tools()).tools), meta


# What the Connections page shows from `zyven verify`: the checks that one listing can decide. Stability needs two
# connections, robustness needs calls, and isolation is about where Zyven runs a server, not about the server.
SHOWN_CHECKS = ("handshake", "schemas", "descriptions", "annotations")


def verify_listing(conn: dict[str, Any], tools: list[Any], meta: dict[str, Any], seconds: float) -> dict[str, Any]:
    """The outside-in checks on one tool listing, and the definition hashes the user is approving."""
    from zyven.mcpverify.checks import FAIL, run_checks
    obs = {"target": conn.get("name", ""), "started": True, "seconds": seconds,
           "server": {k: meta.get(k, "") for k in ("name", "version", "protocol")},
           "instructions": meta.get("instructions", ""),
           "tools": [t.model_dump(by_alias=True, exclude_none=True, mode="json") for t in tools]}
    r = run_checks(obs)
    checks = [{"name": c.name, "status": c.status, "detail": c.detail, "findings": c.findings[:6]}
              for c in r.checks if c.name in SHOWN_CHECKS]
    verdict = "FAIL" if any(c["status"] == FAIL for c in checks) else "PASS"
    return {"verify": {"verdict": verdict, "checks": checks, "checked": time.time()}, "pins": r.lock}


async def probe(store: ConnectionStore, cid: str) -> dict[str, Any]:
    """Try the connection; record the tool list (or the error) on it. Never raises for a failing server."""
    conn = store.get(cid)
    if conn.get("oauth") and not conn.get("signed_in"):
        return store.update(cid, tools=None, enabled=False, error="Sign in first.", checked=time.time())
    try:
        started = time.monotonic()
        tools, meta = await asyncio.wait_for(_list_tools(store, cid, conn), PROBE_TIMEOUT_S)
        checked = verify_listing(conn, tools, meta, time.monotonic() - started)
        # A Test is a review: the definitions seen now are the ones a later run must still match (pins).
        changes = {"tools": describe_tools(tools), "error": None, "checked": time.time(), **checked}
        if checked["verify"]["verdict"] == "FAIL" and conn.get("enabled") and not conn.get("verify_override"):
            changes["enabled"] = False  # re-tested and now failing: switched off until the user decides again
        return store.update(cid, **changes)
    except Exception as e:  # noqa: BLE001 - any transport, auth or launch failure is shown to the user
        from zyven.connections.oauth import SignInNeeded, expire_sign_in, leaf_error

        inner = leaf_error(e)
        if isinstance(inner, SignInNeeded):
            msg = expire_sign_in(store, cid)
            return store.update(cid, tools=None, enabled=False, error=msg, checked=time.time())
        msg = f"{type(inner).__name__}: {inner}"
        for v in store.secrets_for(cid).values():  # a server error must not echo a secret back
            msg = msg.replace(v, "***")
        return store.update(cid, tools=None, enabled=False, error=msg[:400], checked=time.time())
