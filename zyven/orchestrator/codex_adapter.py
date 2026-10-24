"""Codex (OpenAI's coding agent CLI) as a Control center runtime: `codex exec --json`, headless.

Codex has its own sandbox. Zyven asks for `workspace-write`: it may change files only in the task folder, and the
system temp folders and the network are switched off with config overrides (checked live on codex-cli 0.163: a write
to the Desktop and, with the overrides, to %TEMP% were refused, and the in-folder write worked). Zyven never offers
`danger-full-access`.

Event format, taken from real runs: thread/turn events, `item.*` events (agent_message, command_execution,
file_change), and a final `turn.completed` with token usage.

Containment note (found when a real task made Codex reach for the user's computer-use and JavaScript plugins to
copy a file to the Desktop): the sandbox covers shell commands only, so Zyven starts Codex with --ignore-user-config
(your plugins, MCP servers and notify hooks are not loaded; your login still is), --ignore-rules, and the computer,
browser and apps features disabled.

Windows note (found the hard way): Codex's sandbox runs commands as a more restricted identity. A task folder with
owner-only permissions, such as one made by Python's tempfile.mkdtemp(), is not writable to it, so Codex reports
"Failed to write file" even inside its own folder. Task folders under the board directory have normal permissions.

The model is whatever Codex is signed in to (a ChatGPT account or an API key); ZYVEN_CODEX_MODEL picks another.
Off unless ZYVEN_ENABLE_CODEX=1.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from zyven.orchestrator.cli_agent import CLIAgentAdapter, run_quiet

MODEL = re.compile(r"[\w./:#\-]{1,100}")
SANDBOXES = ("read-only", "workspace-write")  # danger-full-access is deliberately not an option


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def parse_line(line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
    line = line.strip()
    if not line:
        return False
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        emit("out", line)
        return False
    kind, item = ev.get("type"), ev.get("item") or {}
    itype = item.get("type")
    if kind == "item.started" and itype in ("command_execution", "mcp_tool_call", "web_search"):
        what = item.get("command") or item.get("tool") or item.get("query") or ""
        emit("tool", f"{'shell' if itype == 'command_execution' else itype}({_short(what)})")
    elif kind == "item.completed":
        if itype == "agent_message" and str(item.get("text", "")).strip():
            emit("out", str(item["text"]).strip())
        elif itype == "file_change":
            for c in item.get("changes") or []:
                emit("tool", f"edit({c.get('kind')} {c.get('path')})")
        elif itype == "command_execution" and item.get("exit_code") not in (0, None):
            emit("tool", f"shell failed (exit {item.get('exit_code')}): {_short(item.get('aggregated_output', ''), 120)}")
    elif kind == "turn.completed":
        usage = ev.get("usage") or {}
        totals["in"] += usage.get("input_tokens", 0) or 0
        totals["out"] += usage.get("output_tokens", 0) or 0  # reasoning tokens are already inside output_tokens
    elif kind in ("turn.failed", "error"):
        err = ev.get("error") or ev.get("message") or ev
        emit("error", _short(err.get("message", err) if isinstance(err, dict) else err, 400))
        return True
    return False


class CodexAdapter(CLIAgentAdapter):
    name = "codex"
    label = "Codex"
    binary = "codex"
    env_flag = "ZYVEN_ENABLE_CODEX"
    privacy = "the task text goes to the provider Codex is signed in to (OpenAI by default)"
    project_config_dirs = (".codex",)
    sign_in_help = "Install Codex (`npm i -g @openai/codex`) and run `codex login`."
    open_weight = False
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": True}
    note = ("Codex in headless mode inside its own sandbox: it can change files only in the task folder, "
            "with no network and no access to the temp folders. Proprietary model by default.")

    def command(self, cwd: Path | None = None) -> list[str]:
        exe = self._executable()
        assert exe, "codex is not installed"
        sandbox = os.environ.get("ZYVEN_CODEX_SANDBOX", "workspace-write").strip()
        if sandbox not in SANDBOXES:
            raise ValueError(f"ZYVEN_CODEX_SANDBOX must be one of {', '.join(SANDBOXES)}")
        cmd = [*exe, "exec", "--json", "-s", sandbox,
               "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true",
               "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
               "-c", "sandbox_workspace_write.network_access=false",
               "--skip-git-repo-check", "--ephemeral",
               # The sandbox limits shell commands only. A user's own config can switch on plugins and MCP servers
               # (computer control, a browser, a JavaScript REPL) that act outside it, so none of that is loaded.
               "--ignore-user-config", "--ignore-rules",
               "--disable", "computer_use", "--disable", "browser_use", "--disable", "apps"]
        if os.name == "nt":  # this setting lives in the user's config file, which is ignored above; without it Codex
            cmd += ["-c", "windows.sandbox=unelevated"]  # has no Windows sandbox and treats the disk as read-only
        if cwd is not None:
            cmd += ["-C", str(cwd)]
        model = self.model()
        if model:
            cmd += ["-m", model]
        return [*cmd, "-"]  # "-" reads the prompt from stdin

    def prepare(self, ctx) -> str:
        return (f"codex exec ({os.environ.get('ZYVEN_CODEX_SANDBOX', 'workspace-write')} sandbox: task folder only, no network; "
                f"model: {self.model() or 'Codex default'})")

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        return parse_line(line, emit, totals)

    def sign_in_state(self) -> tuple[bool | None, str]:
        out = run_quiet([*(self._executable() or []), "login", "status"]).strip()
        if not out:
            return None, ""
        first = out.splitlines()[0]
        return ("logged in" in out.lower() and "not logged in" not in out.lower()), first[:120]
