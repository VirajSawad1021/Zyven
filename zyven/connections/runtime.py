"""Give the agent the tools of the connections the user turned on, with a gate on anything that is not read-only."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable

from zyven.agent.mcp_tools import Gate, ToolBox
from zyven.connections.probe import server_for
from zyven.connections.store import ConnectionStore

Emit = Callable[..., None]
AskUser = Callable[[Any], Awaitable[bool]]


def tool_prefix(name: str, taken: set[str]) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()[:20] or "conn"
    prefix, n = f"{slug}__", 2
    while prefix in taken:
        prefix, n = f"{slug}{n}__", n + 1
    return prefix


def make_gate(connection: str, emit: Emit, ask: AskUser) -> Gate:
    """A gate that raises an approval card for one tool call and waits for the user's answer."""
    async def gate(tool: str, arguments: dict[str, Any]) -> bool:
        from zyven.agent.self_extend import ToolApprovalRequest

        req = ToolApprovalRequest(connection=connection, tool=tool, arguments=arguments)
        emit("NEEDS_APPROVAL", detail=f"{connection}: {tool}", request=req.as_dict())
        allowed = await ask(req)
        emit("RESUMED", detail=("approved " if allowed else "denied ") + f"{connection}: {tool}")
        return allowed
    return gate


async def load_enabled(tb: ToolBox, store: ConnectionStore, emit: Emit, ask: AskUser) -> list[str]:
    """Connect every enabled connection. One that fails is reported and skipped; it never stops the task."""
    loaded: list[str] = []
    prefixes: set[str] = set()
    for c in store.list():
        if not c["enabled"]:
            continue
        prefix = tool_prefix(c["name"], prefixes)
        prefixes.add(prefix)
        try:
            names = await tb.add_transport(f"connection:{c['id']}", server_for(store, c["id"], c),
                                           prefix=prefix, gate=make_gate(c["name"], emit, ask))
        except Exception as e:  # noqa: BLE001 - a broken connection must not break the agent
            from zyven.connections.oauth import SignInNeeded, expire_sign_in, leaf_error

            leaf = leaf_error(e)
            detail = expire_sign_in(store, c["id"]) if isinstance(leaf, SignInNeeded) else f"{c['name']}: {type(leaf).__name__}: {str(leaf)[:160]}"
            emit("CONNECTION_FAILED", detail=detail)
            continue
        loaded += names
        emit("CONNECTION_LOADED", detail=f"{c['name']}: {len(names)} tools")
    return loaded
