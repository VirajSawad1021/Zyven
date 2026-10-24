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
import shutil
import subprocess
import threading
from typing import Any, Callable

from zyven.orchestrator.adapters import RUN_TIMEOUT_S, RunContext, RuntimeAdapter, kill_tree

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


class OpenCodeAdapter(RuntimeAdapter):
    name = "opencode"
    label = "OpenCode"
    open_weight = False  # depends on the model the user picks; not verified here
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": True}
    note = ("OpenCode in headless mode, locked to its task folder (no shell, no web). "
            "You choose the model; Zyven does not verify that it is open-weight.")

    def __init__(self, executable: list[str] | None = None) -> None:
        self._exe = executable  # tests point this at a stand-in program
        self._procs: dict[str, subprocess.Popen] = {}

    def _executable(self) -> list[str] | None:
        if self._exe:
            return self._exe
        found = shutil.which("opencode")
        return [found] if found else None

    def available(self) -> tuple[bool, str]:
        if os.environ.get("ZYVEN_ENABLE_OPENCODE") != "1":
            return False, ("Off by default: the task text goes to the model provider OpenCode is set up with. "
                           "Set ZYVEN_ENABLE_OPENCODE=1 to enable.")
        if not self._executable():
            return False, "`opencode` is not on PATH. Install it from opencode.ai and run `opencode auth login`."
        return True, ""

    def command(self) -> list[str]:
        exe = self._executable()
        assert exe, "opencode is not installed"
        cmd = [*exe, "run", "--standalone", "--format", "json"]
        model = os.environ.get("ZYVEN_OPENCODE_MODEL", "").strip()
        if model:
            if not MODEL.fullmatch(model):
                raise ValueError(f"ZYVEN_OPENCODE_MODEL looks wrong: {model!r}")
            cmd += ["-m", model]
        return cmd

    def run(self, ctx: RunContext) -> int:
        rid = ctx.run["id"]
        if ctx.run["repo_url"] and (ctx.cwd / ".opencode").exists():
            ctx.emit("error", "this repository ships its own OpenCode settings (.opencode); refusing to run it with them")
            return 2
        allow_shell = os.environ.get("ZYVEN_OPENCODE_ALLOW_SHELL") == "1"
        (ctx.cwd / "opencode.json").write_text(json.dumps(permission_config(allow_shell), indent=2), encoding="utf-8")
        cmd = self.command()
        ctx.emit("info", f"opencode run ({'shell ALLOWED on this machine' if allow_shell else 'no shell, no web, folder only'}; "
                         f"model: {os.environ.get('ZYVEN_OPENCODE_MODEL') or 'OpenCode default'})")
        # OpenCode takes its project folder from $PWD when it is set, so a parent shell's PWD would silently point it
        # (and the permission file we just wrote) at the wrong folder. Pin it to the task folder.
        env = {**os.environ, "PWD": str(ctx.cwd)}
        env.pop("OLDPWD", None)
        p = subprocess.Popen(cmd, cwd=ctx.cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        self._procs[rid] = p
        killer = threading.Timer(RUN_TIMEOUT_S, lambda: self.cancel(rid))
        killer.start()
        totals = {"in": 0, "out": 0, "cost": 0.0}
        failed = False
        try:
            assert p.stdin is not None and p.stdout is not None
            p.stdin.write(ctx.run["prompt"])
            p.stdin.close()
            for line in p.stdout:
                failed = parse_line(line, ctx.emit, totals) or failed
            code = p.wait()
            ctx.emit("info", f"done: {int(totals['in'])} in / {int(totals['out'])} out tokens"
                             + (f", ${totals['cost']:.4f}" if totals["cost"] else ""))
            return code or (1 if failed else 0)
        finally:
            killer.cancel()
            self._procs.pop(rid, None)

    def cancel(self, run_id: str) -> None:
        p = self._procs.get(run_id)
        if p and p.poll() is None:
            kill_tree(p)
