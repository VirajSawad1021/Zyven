"""Claude Code as a Control center runtime: `claude -p --output-format stream-json`, headless.

The prompt goes on stdin. Guard rails: a small tool allowlist (no shell by default), `acceptEdits` so edits are
allowed inside the task folder only, the repository's own settings ignored (`--setting-sources user`, so a checked-out
repo cannot bring hooks), no saved session, and a spending cap. Override with ZYVEN_CLAUDE_TOOLS (comma separated)
and ZYVEN_CLAUDE_MAX_USD. Proprietary model: an optional feature, not used for submission results.

Needs `claude` to be logged in (`claude auth status`); off unless ZYVEN_ENABLE_CLAUDE=1.
Not run live on this machine yet: it was not logged in. The event parser follows the format of a real event stream
(system init, assistant messages with text and tool_use blocks, a final result with usage).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from zyven.orchestrator.cli_agent import CLIAgentAdapter, run_quiet

DEFAULT_TOOLS = "Read,Write,Edit,Glob,Grep"


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def parse_stream_line(line: str, emit: Callable[[str, str], None]) -> bool:
    """Turn one Claude Code stream-json line into run events. Returns True when the run reported an error."""
    line = line.strip()
    if not line:
        return False
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        emit("out", line)  # not JSON: show it as plain output
        return False
    kind = msg.get("type")
    if kind == "assistant":
        for block in (msg.get("message") or {}).get("content") or []:
            if block.get("type") == "text" and block.get("text", "").strip():
                emit("out", block["text"].strip())
            elif block.get("type") == "tool_use":
                emit("tool", f"{block.get('name')}({_short(block.get('input', {}))})")
    elif kind == "result":
        usage = msg.get("usage") or {}
        bits = [f"{usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out tokens"]
        if msg.get("total_cost_usd") is not None:
            bits.append(f"${msg['total_cost_usd']:.4f}")
        emit("info", "done: " + ", ".join(bits))
        if msg.get("result"):
            emit("out", str(msg["result"]).strip())
        return bool(msg.get("is_error"))
    return False


class ClaudeCodeAdapter(CLIAgentAdapter):
    name = "claude"
    label = "Claude Code"
    binary = "claude"
    env_flag = "ZYVEN_ENABLE_CLAUDE"
    privacy = "the task text goes to Anthropic (a proprietary model)"
    project_config_dirs = (".claude",)
    sign_in_help = "Install Claude Code and log in with `claude`, then `/login`."
    open_weight = False
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": True}
    note = ("Claude Code in headless mode with a restricted tool set (no shell), edits only in the task folder, "
            "and a spending cap. Proprietary model: experiments, not submission results.")
    DEFAULT_TOOLS = DEFAULT_TOOLS

    def command(self, cwd: Path | None = None) -> list[str]:
        exe = self._executable()
        assert exe, "claude is not installed"
        tools = os.environ.get("ZYVEN_CLAUDE_TOOLS", DEFAULT_TOOLS)
        cap = os.environ.get("ZYVEN_CLAUDE_MAX_USD", "1.00")
        cmd = [*exe, "-p", "--output-format", "stream-json", "--verbose", "--tools", tools,
               "--permission-mode", "acceptEdits", "--setting-sources", "user", "--no-session-persistence"]
        if self.model():
            cmd += ["--model", self.model()]
        return [*cmd, "--max-budget-usd", cap]

    def prepare(self, ctx) -> str:
        cmd = self.command(ctx.cwd)
        return f"claude -p (tools: {cmd[cmd.index('--tools') + 1]}; cap ${cmd[-1]}; runs on this machine)"

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        return parse_stream_line(line, emit)

    def sign_in_state(self) -> tuple[bool | None, str]:
        out = run_quiet([*(self._executable() or []), "auth", "status"])
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None, ""
        if data.get("loggedIn"):
            return True, f"Logged in ({data.get('authMethod', 'unknown')})."
        return False, "Not logged in. Run `claude`, then `/login`."
