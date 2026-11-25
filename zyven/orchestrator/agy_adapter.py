"""Antigravity's command-line agent (`agy`) as a Control center runtime: `agy ... --output-format stream-json --print`.

NO ANSWER SEEN YET. agy 1.1.9 (2026-10) printed one `{"event":"init", ...}` line and then waited for every prompt and
model. Re-checked with agy 1.5.11 on 2026-11-21: a "reply ok" prompt still printed nothing, and agy's own log
(`--log-file`) showed why: "Resource has been exhausted (e.g. check quota)". agy retries silently instead of reporting
it, so an exhausted account looks like a hang. Its `--print-timeout` then ends the run with
`AGY_ERROR: {..."reason":"print_timeout"}` on stderr. So the wait seen so far is the account's quota, not print mode,
and the parser below is still a guess until an answer is seen. --dangerously-skip-permissions is deliberately not used.
Because a stuck program would hold the queue, this adapter has a short idle timeout. Re-test with ZYVEN_AGY_LIVE=1
when the account has quota.

Guard rails from its own options: `--mode accept-edits` and `--sandbox`; never `--dangerously-skip-permissions`.
`--print` is passed last, directly before the prompt, so the prompt is read correctly whether the flag takes a value
or not. The program is native (no shell in between), so the prompt can safely be an argument.
Off unless ZYVEN_ENABLE_AGY=1.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from zyven.orchestrator.cli_agent import CLIAgentAdapter, run_quiet

MODEL = re.compile(r"[\w./:#\-]{1,100}")
TEXT_KEYS = ("text", "result", "content", "message", "delta")


def _find_text(value: Any, depth: int = 0) -> str:
    """Best effort: the first readable string in an event, looking at the usual keys."""
    if isinstance(value, str):
        return value
    if depth > 3:
        return ""
    if isinstance(value, dict):
        for k in TEXT_KEYS:
            if k in value:
                found = _find_text(value[k], depth + 1)
                if found.strip():
                    return found
    if isinstance(value, list):
        return "\n".join(t for t in (_find_text(v, depth + 1) for v in value) if t.strip())
    return ""


def parse_line(line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
    line = line.strip()
    if not line:
        return False
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        emit("out", line)
        return False
    if not isinstance(ev, dict):
        emit("out", line[:300])
        return False
    usage = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}
    totals["in"] += usage.get("input_tokens", 0) or 0
    totals["out"] += usage.get("output_tokens", 0) or 0
    kind = str(ev.get("type", ""))
    if "error" in kind.lower():
        emit("error", (_find_text(ev) or line)[:400])
        return True
    if "tool" in kind.lower():
        emit("tool", (ev.get("name") or ev.get("tool") or kind) + "(" + json.dumps(ev.get("input", ev.get("args", {})))[:140] + ")")
        return False
    text = _find_text(ev).strip()
    if text:
        emit("out", text)
    return False


class AgyAdapter(CLIAgentAdapter):
    name = "agy"
    label = "Antigravity"
    binary = "agy"
    env_flag = "ZYVEN_ENABLE_AGY"
    privacy = "the task text goes to Google (the provider Antigravity is signed in to)"
    stdin_prompt = False
    idle_timeout_s = 120
    project_config_dirs = (".agy", ".antigravity")
    sign_in_help = "Install Antigravity's CLI and launch `agy` once with no arguments to sign in."
    open_weight = False
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": False}
    note = ("Antigravity's CLI in print mode. Experimental: no answer seen yet. On the development machine it waited "
            "without output because the account's quota was exhausted (agy retries silently), so runs are stopped "
            "after 2 minutes of silence.")

    def command(self, cwd: Path | None = None, full: bool = False, hub: dict[str, str] | None = None) -> list[str]:
        exe = self._executable()
        assert exe, "agy is not installed"
        cmd = [*exe, "--output-format", "stream-json", "--mode", "accept-edits", "--sandbox"]
        model = self.model()
        if model:
            cmd += ["--model", model]
        return [*cmd, "--print"]  # the prompt is appended after this flag

    def prepare(self, ctx) -> str:
        return f"agy --print (accept-edits mode, sandbox on; model: {self.model() or 'agy default'})"

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        return parse_line(line, emit, totals)

    def sign_in_state(self) -> tuple[bool | None, str]:
        out = run_quiet([*(self._executable() or []), "models"], timeout=25)
        if not out.strip():
            return None, ""
        if "sign in" in out.lower():
            return False, "Not signed in. Launch `agy` once with no arguments to sign in."
        return True, "Signed in."
