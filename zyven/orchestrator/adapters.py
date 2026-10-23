"""Runtime adapters for the Control center: one interface, any agent.

An adapter receives a task and a working folder, streams events back, can be cancelled, and returns an exit
code. The Control center owns everything else (queue, schedule, repeat, repo checkout, file diff, status), so a
new agent type only has to implement `run` and `cancel`.

  docker  a shell command in a locked-down container (network off by default)
  claude  Claude Code in headless mode, on the host, with a restricted tool set; proprietary, so it is
          off unless ZYVEN_ENABLE_CLAUDE=1

The built-in Zyven agent is not an adapter: it runs as a board card and the Control center mirrors its status.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RUN_TIMEOUT_S = 900


@dataclass
class RunContext:
    run: dict[str, Any]          # the run row (id, prompt, image, network, memory, cpus, ...)
    workdir: Path                # the run's own folder; the repo checkout, if any, is `workdir / "repo"`
    cwd: Path                    # where the task should start: the checkout when there is one, else workdir
    emit: Callable[[str, str], None]   # emit(kind, text): kinds are "info", "out", "tool", "error"
    cancelled: Callable[[], bool]


class RuntimeAdapter:
    name = ""
    label = ""
    open_weight = True
    exposes: dict[str, bool] = {}
    note = ""

    def available(self) -> tuple[bool, str]:
        """(usable now, reason when not). The UI lists unavailable runtimes with the reason."""
        return True, ""

    def run(self, ctx: RunContext) -> int:
        raise NotImplementedError

    def cancel(self, run_id: str) -> None:
        """Stop a running task. Best effort; must be safe to call when nothing is running."""

    def info(self) -> dict[str, Any]:
        ok, why = self.available()
        return {"label": self.label, "open_weight": self.open_weight, "available": ok,
                "exposes": dict(self.exposes), "note": self.note if ok else (why or self.note)}


class DockerAdapter(RuntimeAdapter):
    name = "docker"
    label = "Docker command"
    exposes = {"live_output": True, "tool_calls": False, "approvals": False, "file_changes": True, "tokens": False}
    note = "Runs any shell command in a container with limits and a before/after file diff."

    def run(self, ctx: RunContext) -> int:
        r = ctx.run
        rid = r["id"]
        cmd = ["docker", "run", "--rm", "--name", f"zyven-run-{rid}", "--memory", r["memory"], "--cpus", r["cpus"],
               "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "-v", f"{ctx.workdir}:/work", "-w", "/work/repo" if r["repo_url"] else "/work"]
        if not r["network"]:
            cmd += ["--network", "none"]
        cmd += [r["image"], "sh", "-c", r["prompt"]]
        ctx.emit("info", f"docker run {r['image']} (network {'on' if r['network'] else 'off'}, "
                         f"{r['memory']} / {r['cpus']} cpu)")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        killer = threading.Timer(RUN_TIMEOUT_S, lambda: self.cancel(rid))
        killer.start()
        try:
            for line in p.stdout:  # type: ignore[union-attr]
                ctx.emit("out", line.rstrip("\n"))
            return p.wait()
        finally:
            killer.cancel()

    def cancel(self, run_id: str) -> None:
        subprocess.run(["docker", "kill", f"zyven-run-{run_id}"], capture_output=True)


class ClaudeCodeAdapter(RuntimeAdapter):
    """Claude Code, headless (`claude -p --output-format stream-json`).

    It runs on the host because it needs the user's own login, so the guard rails are its own: a small tool
    allowlist (no shell by default), a working folder of its own, a spending cap and no saved session.
    Override with ZYVEN_CLAUDE_TOOLS (comma separated) and ZYVEN_CLAUDE_MAX_USD.
    """

    name = "claude"
    label = "Claude Code"
    open_weight = False
    exposes = {"live_output": True, "tool_calls": True, "approvals": False, "file_changes": True, "tokens": True}
    note = "Claude Code in headless mode with a restricted tool set. Proprietary model: experiments, not submission results."
    DEFAULT_TOOLS = "Read,Write,Edit,Glob,Grep"

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}

    def available(self) -> tuple[bool, str]:
        if os.environ.get("ZYVEN_ENABLE_CLAUDE") != "1":
            return False, "Off by default (proprietary model). Set ZYVEN_ENABLE_CLAUDE=1 to enable."
        if not shutil.which("claude"):
            return False, "`claude` is not on PATH. Install Claude Code and log in with `claude`."
        return True, ""

    def command(self, prompt: str) -> list[str]:
        tools = os.environ.get("ZYVEN_CLAUDE_TOOLS", self.DEFAULT_TOOLS)
        cap = os.environ.get("ZYVEN_CLAUDE_MAX_USD", "1.00")
        return ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--tools", tools,
                "--no-session-persistence", "--max-budget-usd", cap]

    def run(self, ctx: RunContext) -> int:
        rid = ctx.run["id"]
        cmd = self.command(ctx.run["prompt"])
        ctx.emit("info", f"claude -p (tools: {cmd[cmd.index('--tools') + 1]}; cap ${cmd[-1]}; runs on the host)")
        p = subprocess.Popen(cmd, cwd=ctx.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        self._procs[rid] = p
        killer = threading.Timer(RUN_TIMEOUT_S, lambda: self.cancel(rid))
        killer.start()
        failed = False
        try:
            for line in p.stdout:  # type: ignore[union-attr]
                failed = parse_stream_line(line, ctx.emit) or failed
            code = p.wait()
            return code or (1 if failed else 0)
        finally:
            killer.cancel()
            self._procs.pop(rid, None)

    def cancel(self, run_id: str) -> None:
        p = self._procs.get(run_id)
        if p and p.poll() is None:
            p.kill()


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


def default_adapters() -> dict[str, RuntimeAdapter]:
    return {a.name: a for a in (DockerAdapter(), ClaudeCodeAdapter())}
