"""Connect to MCP servers and expose their tools in OpenAI function-calling format."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp import Client
from mcp.client.stdio import StdioServerParameters


@dataclass
class MCPServerSpec:
    """How to launch one skill's MCP server over stdio."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] | None = None

    @classmethod
    def python_script(cls, name: str, script: str | Path) -> "MCPServerSpec":
        """Runs on the host with the caller's permissions: for trusted, hand-written servers only."""
        return cls(name=name, command=sys.executable, args=[str(script)])

    @classmethod
    def sandboxed(cls, name: str, skill_dir: str | Path, source_checkout: str | Path | None = None) -> "MCPServerSpec":
        """Runs a compiled skill inside the same locked-down container its verification gates used: no network,
        non-root, read-only, capabilities dropped, resource limits. The skill and its pinned source checkout are
        mounted read-only at /skill and /src, exactly as during verification."""
        from zyven.sandbox.runner import SandboxPolicy, stdio_command

        mounts = {Path(skill_dir): "/skill"}
        env = {}
        if source_checkout:
            mounts[Path(source_checkout)] = "/src"
            env["PYTHONPATH"] = "/src"
        argv = stdio_command(["python", "/skill/server.py"], mounts, SandboxPolicy(extra_env=env), workdir="/skill")
        return cls(name=name, command=argv[0], args=argv[1:])


# A gate decides whether one specific call may go ahead: gate(tool_name, arguments) -> allowed.
Gate = Callable[[str, dict[str, Any]], Awaitable[bool]]


class ToolBox:
    """Holds live MCP connections; tools can be added while an agent is running (hot-load)."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._route: dict[str, str] = {}  # tool name -> server name
        self._orig: dict[str, str] = {}  # tool name -> the name the server knows it by (differs when prefixed)
        self._gates: dict[str, Gate] = {}  # tools that need a yes before every call
        self._native: dict[str, Callable[[dict[str, Any]], str]] = {}  # built-in tools: plain functions
        self.openai_tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> "ToolBox":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.__aexit__(*exc)

    async def add_server(self, spec: MCPServerSpec) -> list[str]:
        params = StdioServerParameters(command=spec.command, args=spec.args, cwd=spec.cwd, env=spec.env)
        return await self.add_transport(spec.name, params)

    async def add_transport(self, name: str, server: Any, prefix: str = "", gate: Gate | None = None) -> list[str]:
        """Connect any MCP server (stdio parameters, or a transport). With a gate, every tool the server does not
        mark read-only asks the gate before each call; a tool with no hint counts as not read-only. `prefix` keeps
        tool names from different servers apart."""
        from zyven.connections.probe import needs_approval

        client = await self._stack.enter_async_context(Client(server, read_timeout_seconds=60))
        self._clients[name] = client
        listing = await client.list_tools()
        added = []
        for tool in listing.tools:
            public = (prefix + tool.name)[:64]
            if public in self._route:
                continue
            self._route[public] = name
            self._orig[public] = tool.name
            if gate is not None and needs_approval(tool):
                self._gates[public] = gate
            self.openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": public,
                        "description": tool.description or "",
                        "parameters": tool.input_schema or {"type": "object", "properties": {}},
                    },
                }
            )
            added.append(public)
        return added

    def add_native(self, name: str, description: str, parameters: dict[str, Any],
                   fn: Callable[[dict[str, Any]], str], gate: Gate | None = None) -> None:
        """A built-in tool: `fn(arguments)` returns the text the model sees, or raises ValueError with a message
        the model can act on. With a gate, every call waits for a yes first."""
        self._native[name] = fn
        self._route[name] = "native"
        if gate is not None:
            self._gates[name] = gate
        self.openai_tools.append({"type": "function", "function": {"name": name, "description": description,
                                                                    "parameters": parameters}})

    @property
    def tool_names(self) -> list[str]:
        return list(self._route)

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Returns (ok, text). Errors are returned to the model as text, never raised into the loop."""
        server = self._route.get(name)
        if server is None:
            return False, f"Unknown tool {name!r}. Available: {', '.join(self._route) or 'none'}"
        gate = self._gates.get(name)
        if gate is not None and not await gate(name, arguments):
            return False, "Denied: the user did not approve this action, so it was not run. Do not retry it."
        if name in self._native:
            try:
                return True, await asyncio.to_thread(self._native[name], arguments)
            except ValueError as e:  # a refusal the model can fix: bad path, bad argument
                return False, str(e)
            except Exception as e:  # noqa: BLE001 - never raise into the agent loop
                return False, f"Tool {name} failed: {e}"
        try:
            result = await self._clients[server].call_tool(self._orig.get(name, name), arguments)
        except Exception as e:  # noqa: BLE001 - surface any transport/tool failure to the model
            return False, f"Tool {name} failed: {e}"
        if result.structured_content is not None:
            text = json.dumps(result.structured_content, ensure_ascii=False)
        else:
            text = "\n".join(getattr(c, "text", "") for c in result.content)
        return not result.is_error, text
