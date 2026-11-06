"""Connect to an MCP server (a command over stdio, or a URL) and record what it says and does.

No tool is called unless probes are asked for. Probes only send input that the tool's own schema rejects (missing
required parameters, or a wrong type), so a correct server answers with an error and does nothing; a careless one
might still act on it, which is why probes are opt-in.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

TIMEOUT_S = 60.0


def _tool_dict(tool: Any) -> dict[str, Any]:
    return tool.model_dump(by_alias=True, exclude_none=True, mode="json")


def _wrong_type(schema: dict[str, Any]) -> Any:
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    return {"string": 12345, "integer": "not a number", "number": "not a number", "boolean": "maybe",
            "array": "not a list", "object": "not an object"}.get(t or "", None)


def invalid_inputs(tool: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Arguments the tool's own schema forbids: (what, arguments)."""
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = [r for r in schema.get("required") or [] if r in props]
    out: list[tuple[str, dict[str, Any]]] = []
    if required:
        out.append(("missing required parameters", {}))
        first = required[0]
        bad = _wrong_type(props[first]) if isinstance(props[first], dict) else None
        if bad is not None:
            out.append((f"wrong type for {first!r}", {first: bad}))
    return out


def server_from(command: list[str] | None, url: str | None, headers: dict[str, str] | None = None,
                env: dict[str, str] | None = None, docker_image: str | None = None,
                mounts: dict[Path, str] | None = None, container: str | None = None,
                network: bool = False) -> tuple[Any, bool, str]:
    """(what Client connects to, sandboxed?, a label for the report)."""
    if url:
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        return (streamable_http_client(url, http_client=create_mcp_http_client(headers=headers or None)), False, url)
    if not command:
        raise ValueError("give a server command (after --) or --url")
    label = " ".join(command)
    if docker_image:
        from zyven.sandbox.runner import SandboxPolicy, stdio_command
        mounts = {Path(h).resolve(): c for h, c in (mounts or {}).items()}  # read-only, like the compile gates
        workdir = next(iter(mounts.values()), "/tmp")
        argv = stdio_command(command, mounts, SandboxPolicy(image=docker_image, extra_env=env or {}, network=network),
                             workdir=workdir, name=container)
        return StdioServerParameters(command=argv[0], args=argv[1:]), True, f"{label} (in {docker_image})"
    # env=None: the SDK passes only a safe default environment (PATH, HOME, ...), never this shell's secrets
    return StdioServerParameters(command=command[0], args=command[1:], env=env or None), False, label


async def observe(make_server, label: str, sandboxed: bool, probe: bool = False, twice: bool = True,
                  timeout: float = TIMEOUT_S) -> dict[str, Any]:
    """make_server() returns a fresh transport/params each call (a second connection needs a new one)."""
    obs: dict[str, Any] = {"target": label, "sandboxed": sandboxed, "started": False}
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            async with Client(make_server(), read_timeout_seconds=timeout) as client:
                info = client.server_info
                obs["server"] = {"name": getattr(info, "name", ""), "version": getattr(info, "version", ""),
                                 "protocol": str(client.protocol_version or "")}
                obs["instructions"] = client.instructions or ""
                tools = (await client.list_tools()).tools
                obs["tools"] = [_tool_dict(t) for t in tools]
                obs["started"] = True
                obs["seconds"] = round(time.monotonic() - started, 2)
                if probe:
                    obs["probes"] = []
                    for t in obs["tools"]:
                        for what, args in invalid_inputs(t):
                            entry = {"tool": t["name"], "kind": what, "ok": False}
                            try:
                                res = await client.call_tool(t["name"], args)
                                entry["ok"] = bool(res.is_error)
                                entry["detail"] = f"{what}: rejected" if res.is_error else f"{what}: ACCEPTED"
                            except Exception as e:  # noqa: BLE001
                                entry["ok"] = _is_protocol_error(e)  # a JSON-RPC error is a clean rejection too
                                entry["detail"] = (f"{what}: rejected ({type(e).__name__})" if entry["ok"]
                                                   else f"{what}: connection failed ({_why(e)})")
                            obs["probes"].append(entry)
                    if obs["probes"]:  # still answering after bad input? Repeat one probe: a tool call is never
                        first = obs["tools"][0]  # served from the client's cache (list_tools can be; ping was removed)
                        try:
                            await client.call_tool(first["name"], invalid_inputs(first)[0][1] if invalid_inputs(first) else {})
                            obs["alive_after_probes"] = True
                        except Exception as e:  # noqa: BLE001
                            obs["alive_after_probes"] = _is_protocol_error(e)
    except Exception as e:  # noqa: BLE001
        if not obs["started"]:
            obs["error"] = _why(e)
            return obs
        obs.setdefault("error", _why(e))
    if twice and obs["started"]:
        try:
            async with asyncio.timeout(timeout):
                async with Client(make_server(), read_timeout_seconds=timeout) as client:
                    obs["tools_again"] = [_tool_dict(t) for t in (await client.list_tools()).tools]
        except Exception as e:  # noqa: BLE001
            obs["second_connection_error"] = _why(e)
    return obs


def _is_protocol_error(e: BaseException) -> bool:
    """The server answered with a JSON-RPC error (it is alive), as opposed to the connection breaking."""
    from mcp.shared.exceptions import MCPError
    return isinstance(e, MCPError)


def _why(e: BaseException) -> str:
    """Exception groups from anyio hide the real cause one or more levels down."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    if isinstance(e, TimeoutError):
        return "timed out"
    return f"{type(e).__name__}: {str(e)[:300]}"
