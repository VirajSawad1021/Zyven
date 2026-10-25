"""Qoder CLI as a Control center runtime: `qodercli -p -o stream-json`, headless.

Qoder CLI offers several model families, including open-weight ones (Qwen and DeepSeek families on the account used to
build this). Zyven does not verify which weights or host answer, so the runtime is not marked open-weight; the model is
the user's choice on the Control center page (ZYVEN_QODER_MODEL also works).

The prompt goes on stdin. Guard rails: a small built-in tool allowlist (no shell, no web), `accept_edits` so edits are
allowed in the task folder, and Zyven's tools through an MCP config file in the task folder (the token stays out of
argv). The event stream has the same shape as Claude Code's, so the parser is shared.

Needs `qodercli` signed in (`qodercli status`); off unless ZYVEN_ENABLE_QODER=1. The program is found on PATH, or at
the path in ZYVEN_QODERCLI.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable

from zyven.orchestrator.claude_adapter import parse_stream_line
from zyven.orchestrator.cli_agent import CLIAgentAdapter, run_quiet

DEFAULT_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")


class QoderAdapter(CLIAgentAdapter):
    name = "qoder"
    label = "Qoder CLI"
    binary = "qodercli"
    env_flag = "ZYVEN_ENABLE_QODER"
    privacy = "the task text goes to Qoder and the model it serves"
    project_config_dirs = (".qoder",)
    scaffold_files = (".zyven-mcp.json",)  # the tool config Zyven writes; not part of the user's results
    sign_in_help = "Install it with `npm install -g @qoder-ai/qodercli`, then run `qodercli` and `/login`."
    open_weight = False  # the model family can be open-weight; the host and exact weights are not verified here
    supports_full_access = True
    supports_hub = True
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": False}  # it reports 0
    note = ("Qoder CLI in headless mode with a restricted tool set (no shell, no web), edits in the task folder. "
            "Pick an open-weight model (for example a Qwen or DeepSeek one) on the Control center page.")

    def _executable(self) -> list[str] | None:
        if self._exe:
            return self._exe
        override = os.environ.get("ZYVEN_QODERCLI")
        if override and Path(override).exists():
            return [override]
        found = shutil.which(self.binary)
        return [found] if found else None

    def command(self, cwd: Path | None = None, full: bool = False, hub: dict[str, str] | None = None) -> list[str]:
        exe = self._executable()
        assert exe, "qodercli is not installed"
        cmd = [*exe, "-p", "-o", "stream-json", "--permission-mode", "bypass_permissions" if full else "accept_edits"]
        if self.model():
            cmd += ["-m", self.model()]
        if hub and cwd is not None:
            cmd += ["--mcp-config", str(Path(cwd) / ".zyven-mcp.json"), "--strict-mcp-config",
                    "--allowed-tools", "mcp__zyven"]
        if not full:
            cmd += ["--tools", *DEFAULT_TOOLS]  # variadic: it must be the last option
        return cmd

    def prepare(self, ctx) -> str:
        full = bool(ctx.run.get("full_access"))
        if ctx.hub:
            (ctx.cwd / ".zyven-mcp.json").write_text(json.dumps({"mcpServers": {"zyven": {
                "type": "http", "url": ctx.hub["url"], "headers": {"Authorization": f"Bearer {ctx.hub['token']}"}}}}),
                encoding="utf-8")
        return (f"qodercli -p ({'NO RESTRICTIONS, ' if full else 'tools: ' + ', '.join(DEFAULT_TOOLS) + '; '}"
                f"model: {self.model() or 'Qoder default'}; runs on this machine)")

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        def once(kind: str, text: str) -> None:  # Qoder repeats the final answer in its result line: show it once
            if kind == "info" and text.startswith("done:"):
                return  # Qoder reports zero usage; the shared runner prints its own totals line
            if kind == "out":
                if text == totals.get("_out"):
                    return
                totals["_out"] = text  # type: ignore[assignment]
            emit(kind, text)

        return parse_stream_line(line, once)

    def sign_in_state(self) -> tuple[bool | None, str]:
        out = run_quiet([*(self._executable() or []), "status"])
        if "Not logged in" in out:
            return False, "Not logged in. Run `qodercli`, then `/login`."
        if "Username:" in out or "Email:" in out:
            return True, "Signed in."
        return None, ""
