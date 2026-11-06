"""`zyven mcp`: Zyven's verified skills as a plain stdio MCP server, for any coding agent, without the board.

    claude mcp add zyven -- zyven mcp            # Claude Code
    codex mcp add zyven -- zyven mcp             # Codex
    (any MCP client: command `zyven`, args `mcp`)

The agent starts this process itself; nothing else has to be running. It serves the same tools as the board's hub
(`HubSession`): every verified skill in the library, each in its locked-down Docker sandbox (no network, read-only),
plus the `zyven_status` tool. Connected services (Notion, GitHub, ...) are added only with `--connections`. The board's
approval cards are not available in this mode, so the agent's own permission prompt is what stands before a tool that
changes something; that is why they are off by default.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from zyven.connections.store import ConnectionStore
from zyven.hub.hub import HubSession
from zyven.memory.skills import SkillLibrary

INSTRUCTIONS = ("Zyven's verified skills: tools compiled from pinned open-source libraries and checked by six sandbox "
                "gates. Prefer them over guessing for exact computations such as validation, conversion and comparison. "
                "Call zyven_status to see which skills and services are available.")
READ_ONLY = types.ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def _note(text: str) -> None:
    print(f"[zyven mcp] {text}", file=sys.stderr, flush=True)  # stdout carries the protocol


def build_server(board_dir: Path, connections: bool = False, only: list[str] | None = None) -> tuple[Server, Any]:
    library = SkillLibrary(board_dir / "library")
    skills = [s for s in library.list() if not only or s.name in only]
    store = ConnectionStore(board_dir) if connections else _NoConnections()
    session: dict[str, HubSession] = {}
    skill_tools: set[str] = set()

    def get() -> HubSession:
        if "s" not in session:  # created inside the server's event loop (its sources start tasks)
            session["s"] = HubSession("stdio", store, [s.server_spec() for s in skills],
                                      approve=lambda *_: True, notify=lambda _run, msg: _note(msg))
        return session["s"]

    async def list_tools(ctx, params) -> types.ListToolsResult:
        hub = get()
        listed = await hub.tools()
        if not skill_tools:
            for src in hub.sources:
                if src.label.startswith("skill ") and src.toolbox:
                    skill_tools.update(t["function"]["name"] for t in src.toolbox.openai_tools)
        return types.ListToolsResult(tools=[
            types.Tool(name=t["function"]["name"], description=t["function"].get("description", ""),
                       input_schema=t["function"].get("parameters") or {"type": "object", "properties": {}},
                       annotations=READ_ONLY if t["function"]["name"] in skill_tools or
                       t["function"]["name"] == "zyven_status" else None)
            for t in listed])

    async def call_tool(ctx, params) -> types.CallToolResult:
        ok, text = await get().call(params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=not ok)

    server = Server("zyven", version="1", instructions=INSTRUCTIONS, on_list_tools=list_tools, on_call_tool=call_tool)
    _note(f"{len(skills)} verified skill(s) from {board_dir / 'library'}"
          + (": " + ", ".join(s.name for s in skills) if skills else " (compile some with `zyven compile` or the board)")
          + ("; connected services ON: tools that change something are gated only by your agent's own permission prompt"
             if connections else "; connected services off (add --connections to include them)"))
    return server, session


class _NoConnections:
    def list(self) -> list[dict]:
        return []


async def serve(board_dir: Path, connections: bool = False, only: list[str] | None = None) -> None:
    server, session = build_server(board_dir, connections, only)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        if "s" in session:
            await session["s"].close()


def main(board_dir: Path, connections: bool = False, only: list[str] | None = None) -> None:
    asyncio.run(serve(board_dir, connections, only))
