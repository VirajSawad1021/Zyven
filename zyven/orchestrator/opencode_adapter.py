"""OpenCode (https://opencode.ai) as a Control center runtime: `opencode run --format json`, headless.

OpenCode is open source and works with many models, including open-weight ones; which model answers is the
user's choice, so Zyven does not claim the run is open-weight.

By default a headless OpenCode runs shell commands and writes outside its working folder without asking (checked
on v2.1.4). So the adapter writes an `opencode.json` into the task folder that denies shell, access outside the
folder and web access. Only ZYVEN_OPENCODE_ALLOW_SHELL=1 turns the shell back on, and then it runs on this
machine with the user's permissions, not in a container.

The prompt is sent on stdin, never on the command line, so nothing the user typed passes through a shell.
The child's PWD is pinned to the task folder: OpenCode trusts $PWD over the real working directory (found by a live
test, where it wrote into the parent's folder and ignored the permission file).
Off unless ZYVEN_ENABLE_OPENCODE=1 (the task text goes to whatever model provider OpenCode is set up with).
Model: ZYVEN_OPENCODE_MODEL (provider/model), else OpenCode's own default.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from zyven.orchestrator.adapters import RunContext
from zyven.orchestrator.cli_agent import CLIAgentAdapter, run_quiet

MODEL = re.compile(r"[\w./:#\-]{1,100}")


def permission_config(allow_shell: bool = False) -> dict[str, Any]:
    """What OpenCode may do in the task folder. Anything not listed keeps OpenCode's default."""
    return {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "read": "allow", "edit": "allow", "glob": "allow", "grep": "allow", "list": "allow",
            "bash": "allow" if allow_shell else "deny",
            "external_directory": "deny", "webfetch": "deny", "websearch": "deny",
        },
    }


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def parse_line(line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
    """Turn one OpenCode JSON event into run events and token totals. Returns True when the run reported an error."""
    line = line.strip()
    if not line:
        return False
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        emit("out", line)  # not JSON: show it as plain output
        return False
    kind, part = ev.get("type"), ev.get("part") or {}
    if kind == "text" and str(part.get("text", "")).strip():
        emit("out", str(part["text"]).strip())
    elif kind == "tool_use":
        state = part.get("state") or {}
        failed = state.get("status") == "error"
        emit("tool", f"{part.get('tool')}({_short(state.get('input', {}))})" + (" - blocked or failed" if failed else ""))
    elif kind == "step_finish":
        tokens = part.get("tokens") or {}
        totals["in"] += tokens.get("input", 0) or 0
        totals["out"] += (tokens.get("output", 0) or 0) + (tokens.get("reasoning", 0) or 0)
        totals["cost"] += part.get("cost", 0) or 0
    elif kind == "error":
        emit("error", _short(ev.get("error") or ev, 400))
        return True
    return False


class OpenCodeAdapter(CLIAgentAdapter):
    name = "opencode"
    label = "OpenCode"
    binary = "opencode"
    env_flag = "ZYVEN_ENABLE_OPENCODE"
    privacy = "the task text goes to the model provider OpenCode is set up with"
    project_config_dirs = (".opencode",)
    scaffold_files = ("opencode.json",)  # the permission file Zyven writes; not part of the user's results
    sign_in_help = "Install it from opencode.ai; `opencode auth login` adds your own provider."
    open_weight = False  # depends on the model the user picks; not verified here
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": True}
    note = ("OpenCode in headless mode, locked to its task folder (no shell, no web). "
            "You choose the model; Zyven does not verify that it is open-weight.")

    def command(self, cwd: Path | None = None) -> list[str]:
        exe = self._executable()
        assert exe, "opencode is not installed"
        cmd = [*exe, "run", "--standalone", "--format", "json"]
        model = self.model()
        if model:
            cmd += ["-m", model]
        return cmd

    def prepare(self, ctx: RunContext) -> str:
        allow_shell = os.environ.get("ZYVEN_OPENCODE_ALLOW_SHELL") == "1"
        (ctx.cwd / "opencode.json").write_text(json.dumps(permission_config(allow_shell), indent=2), encoding="utf-8")
        return (f"opencode run ({'shell ALLOWED on this machine' if allow_shell else 'no shell, no web, folder only'}; "
                f"model: {self.model() or 'OpenCode default'})")

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        return parse_line(line, emit, totals)

    def sign_in_state(self) -> tuple[bool | None, str]:
        out = run_quiet([*(self._executable() or []), "auth", "list"])
        if not out:
            return None, ""
        if "No authenticated" in out:
            return None, "No provider signed in; OpenCode's free hosted models still work. `opencode auth login` adds your own."
        return True, "Signed in to a provider."
