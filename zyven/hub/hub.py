"""The Zyven hub: Zyven's tools, offered to any coding agent over MCP.

A coding agent such as Codex or OpenCode brings its own model, so it needs no model API key from Zyven. What it lacks
is what Zyven has: the services the user connected (Notion, GitHub, ...) and the verified skills compiled from open
source. The hub serves both over MCP (streamable HTTP) so an agent started by the Control center can use them.

  * Each task gets its own short-lived bearer token; the hub knows which run a request belongs to, and the token stops
    working when the run ends. Nothing else can call the hub.
  * Connected services are loaded for that run with the same prefixes as in the Zyven agent. A tool its server does not
    mark read-only waits for the user's yes before every call, on the board's approval cards. The agent's call simply
    blocks until the user decides (the agent is told the tool call was denied if they say no).
  * Verified skills are served from the library; they run in their Docker sandbox, so they need no approval.

The hub keeps one ToolBox per source (each connection, each skill) per run, each opened and closed by a task of its own
(MCP client connections must be opened and closed by the same task, and the HTTP handlers run in many), and starts
them in parallel: an agent gives a tool server only seconds to answer its first request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable

from mcp import types
from mcp.server.lowlevel import Server

from zyven.agent.mcp_tools import MCPServerSpec, ToolBox
from zyven.connections.oauth import SignInNeeded, expire_sign_in, leaf_error
from zyven.connections.probe import server_for
from zyven.connections.runtime import tool_prefix
from zyven.connections.store import ConnectionStore

log = logging.getLogger("zyven.hub")

# approve(run_id, kind, summary, detail) -> bool: blocks until the user decides (Control.request_approval)
Approve = Callable[[str, str, str, str], bool]
STATUS_NAME = "zyven_status"
STATUS_TOOL = {"type": "function", "function": {
    "name": STATUS_NAME,
    "description": "Report which of Zyven's tools are available and why a service is missing (for example an expired "
                   "sign-in). Call this if a tool you expected, such as a Notion tool, is not in your list.",
    "parameters": {"type": "object", "properties": {}}}}
# A pending approval waits (up to an hour) in a thread. Give those their own pool so a pile of waiting cards can never
# starve the default executor that the rest of the board uses.
_APPROVAL_THREADS = ThreadPoolExecutor(max_workers=64, thread_name_prefix="zyven-approval")
DENIED = "Denied: the user did not approve this action, so it was not run. Do not retry it."


class _Source:
    """One connection or skill: its own ToolBox, opened and closed by one task, loaded in parallel with the others."""

    def __init__(self, label: str, load: Callable[[ToolBox], Awaitable[list[str]]],
                 on_sign_in_expired: Callable[[], str] | None = None) -> None:
        self.label, self._load = label, load
        self.on_sign_in_expired = on_sign_in_expired
        self.toolbox: ToolBox | None = None
        self.error: str | None = None
        self._ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self._close = asyncio.Event()
        self._task = asyncio.create_task(self._own())

    async def _own(self) -> None:
        try:
            async with ToolBox() as tb:
                await self._load(tb)
                self.toolbox = tb
                if not self._ready.done():
                    self._ready.set_result(None)
                await self._close.wait()
        except Exception as e:  # noqa: BLE001 - a broken source must not hide the others
            e = leaf_error(e)
            self.error = e.args[0] if isinstance(e, SignInNeeded) and e.args else f"{type(e).__name__}: {str(e)[:120]}"
            if isinstance(e, SignInNeeded) and self.on_sign_in_expired:
                self.error = self.on_sign_in_expired()
            log.warning("hub: %s unavailable: %s", self.label, e)
            if not self._ready.done():
                self._ready.set_result(None)
        except asyncio.CancelledError:
            if not self._ready.done():
                self._ready.set_result(None)

    async def ready(self) -> None:
        await asyncio.wait_for(asyncio.shield(self._ready), 120)

    async def close(self) -> None:
        self._close.set()
        try:
            await asyncio.wait_for(self._task, 20)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
            self._task.cancel()


class HubSession:
    """One run's tools: every enabled connection and every verified skill, started in parallel and kept until the run ends."""

    def __init__(self, run_id: str, store: ConnectionStore, skills: list[MCPServerSpec], approve: Approve,
                 notify: Callable[[str, str], None] | None = None) -> None:
        self.run_id, self._approve, self._notify = run_id, approve, notify
        self.sources: list[_Source] = []
        prefixes: set[str] = set()
        for c in store.list():
            if not c["enabled"]:
                continue
            prefix = tool_prefix(c["name"], prefixes)
            prefixes.add(prefix)

            async def load_connection(tb: ToolBox, c=c, prefix=prefix) -> list[str]:
                return await tb.add_transport(f"connection:{c['id']}", server_for(store, c["id"], c), prefix=prefix,
                                              gate=self._gate_for(c["name"]))

            self.sources.append(_Source(c["name"], load_connection,
                                        lambda cid=c["id"]: expire_sign_in(store, cid)))
        for spec in skills:
            self.sources.append(_Source(f"skill {spec.name}", lambda tb, spec=spec: tb.add_server(spec)))
        self._route: dict[str, ToolBox] = {}
        self._tools: list[dict[str, Any]] = []
        self._built: asyncio.Task | None = None

    @property
    def notes(self) -> list[str]:
        return [(s.error if s.error and s.error.startswith(s.label) else f"{s.label}: {s.error or 'ready'}") for s in self.sources]

    def _gate_for(self, connection: str):
        async def gate(tool: str, args: dict[str, Any]) -> bool:
            detail = json.dumps(args, ensure_ascii=False)[:3000]
            return await asyncio.get_running_loop().run_in_executor(
                _APPROVAL_THREADS, self._approve, self.run_id, "tool_call", f"{connection}: {tool}", detail)
        return gate

    async def _build(self) -> None:
        self._route, self._tools = {}, []
        await asyncio.gather(*(s.ready() for s in self.sources))
        for s in self.sources:
            if s.toolbox is None:
                continue
            for t in s.toolbox.openai_tools:
                name = t["function"]["name"]
                if name != STATUS_NAME and name not in self._route:  # the status tool's name is Zyven's own
                    self._route[name] = s.toolbox
                    self._tools.append(t)
        for s in self.sources:  # tell the user in the run's log what could not be offered, and why
            if s.error and self._notify:
                self._notify(self.run_id, f"Zyven hub: {s.label} unavailable. {s.error}")
        self._tools.append(STATUS_TOOL)

    async def tools(self) -> list[dict[str, Any]]:
        if self._built is None:
            self._built = asyncio.create_task(self._build())  # its own task: one caller giving up does not stop it
        try:
            await asyncio.shield(self._built)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._built = None  # a failed build is tried again by the next caller instead of hanging them
            raise
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        await self.tools()
        if name == STATUS_NAME:
            return True, "\n".join(self.notes) or "No connections or skills are set up."
        tb = self._route.get(name)
        if tb is None:
            return False, f"Unknown tool {name!r}."
        return await tb.call(name, arguments)

    async def close(self) -> None:
        await asyncio.gather(*(s.close() for s in self.sources), return_exceptions=True)


class ZyvenHub:
    def __init__(self, store: Callable[[], ConnectionStore], skills: Callable[[], list[MCPServerSpec]],
                 approve: Approve, notify: Callable[[str, str], None] | None = None) -> None:
        self._store, self._skills, self._approve, self._notify = store, skills, approve, notify
        self._tokens: dict[str, str] = {}      # token -> run id
        self._sessions: dict[str, HubSession] = {}
        self._lock: asyncio.Lock | None = None
        self.loop: asyncio.AbstractEventLoop | None = None  # the board's event loop, set when the app starts
        self.server = Server("zyven-hub", version="1", on_list_tools=self._list_tools, on_call_tool=self._call_tool,
                             instructions="Zyven's tools: services the user connected and verified skills. "
                                          "Tools that change something wait for the user's approval before they run.")
        self.app = self.server.streamable_http_app(streamable_http_path="/mcp")

    # --- grants -----------------------------------------------------------------------------------------
    def issue(self, run_id: str) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = run_id
        return token

    async def revoke(self, run_id: str) -> None:
        for t in [t for t, r in self._tokens.items() if r == run_id]:
            self._tokens.pop(t, None)
        session = self._sessions.pop(run_id, None)
        if session:
            await session.close()

    def revoke_from_thread(self, run_id: str) -> None:
        """For the Control center's worker thread: stop the run's token and close its sessions on the hub's loop."""
        if self.loop is None:
            for t in [t for t, r in self._tokens.items() if r == run_id]:
                self._tokens.pop(t, None)
            return
        try:
            asyncio.run_coroutine_threadsafe(self.revoke(run_id), self.loop).result(60)
        except Exception as e:  # noqa: BLE001 - the token is already gone; a slow close must not fail the run
            log.warning("hub: closing run %s: %s", run_id, e)

    def run_for(self, token: str) -> str | None:
        return self._tokens.get(token)

    def asgi(self):
        """The hub as an ASGI app that answers only requests carrying a live run token."""
        hub, inner = self, self.app

        async def app(scope, receive, send):
            if scope["type"] == "http":
                headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
                auth = headers.get("authorization", "")
                token = auth[7:] if auth.lower().startswith("bearer ") else ""
                if not token or hub.run_for(token) is None:
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                    await send({"type": "http.response.body", "body": b"invalid or expired Zyven hub token"})
                    return
                scope.setdefault("state", {})["zyven_run"] = hub.run_for(token)
            await inner(scope, receive, send)

        app.session_manager = self.server.session_manager  # type: ignore[attr-defined]
        return app

    # --- sessions ---------------------------------------------------------------------------------------
    async def _session(self, run_id: str) -> HubSession:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if run_id not in self._tokens.values():  # revoked while this request was on its way: do not start tool servers
                raise PermissionError("this run has ended")
            session = self._sessions.get(run_id)
            if session is None:
                session = self._sessions[run_id] = HubSession(run_id, self._store(), self._skills(), self._approve, self._notify)
        return session

    def _run_of(self, ctx) -> str:
        state = ctx.request.scope.get("state", {}) if getattr(ctx, "request", None) else {}
        run_id = state.get("zyven_run")
        if not run_id:
            raise PermissionError("no run for this request")
        return run_id

    # --- MCP handlers -----------------------------------------------------------------------------------
    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        listed = await (await self._session(self._run_of(ctx))).tools()
        tools = [types.Tool(name=t["function"]["name"], description=t["function"].get("description", ""),
                            input_schema=t["function"].get("parameters") or {"type": "object", "properties": {}})
                 for t in listed]
        return types.ListToolsResult(tools=tools)

    async def _call_tool(self, ctx, params) -> types.CallToolResult:
        ok, text = await (await self._session(self._run_of(ctx))).call(params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=not ok)
