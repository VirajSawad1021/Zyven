"""Runtime adapters for the Control center: one interface, any agent.

An adapter receives a task and a working folder, streams events back, can be cancelled, and returns an exit
code. The Control center owns everything else (queue, schedule, repeat, repo checkout, file diff, status), so a
new agent type only has to implement `run` and `cancel`.

  docker  a shell command in a locked-down container (network off by default)
  claude, codex, opencode, agy  command-line coding agents run headless (cli_agent.py and one module each); every
          one is off unless its ZYVEN_ENABLE_* variable is 1
  github  create a repository or an issue with `gh` after approval (github_adapter.py); off unless
          ZYVEN_ENABLE_GITHUB=1

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
    # approve(kind, summary, detail="") -> bool: ask the user before an outward action (send, push, post, create).
    # Blocks until they decide; False when denied, expired or cancelled. Adapters must not act on False.
    approve: Callable[..., bool] = lambda kind, summary, detail="": False


class RuntimeAdapter:
    name = ""
    label = ""
    open_weight = True
    exposes: dict[str, bool] = {}
    note = ""
    supports_full_access = False  # can this runtime be started without its sandbox, on the user's explicit request?

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


def kill_tree(p: subprocess.Popen) -> None:
    """Stop a process and everything it started (agent CLIs launch helpers; killing only the parent leaks them)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.kill()


def __getattr__(name: str):  # the Claude adapter lives in claude_adapter.py; keep the old import path working
    if name in ("ClaudeCodeAdapter", "parse_stream_line"):
        from zyven.orchestrator import claude_adapter
        return getattr(claude_adapter, name)
    raise AttributeError(name)


def default_adapters() -> dict[str, RuntimeAdapter]:
    from zyven.orchestrator.agy_adapter import AgyAdapter  # these import this module, so import them lazily
    from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter
    from zyven.orchestrator.codex_adapter import CodexAdapter
    from zyven.orchestrator.github_adapter import GitHubAdapter
    from zyven.orchestrator.opencode_adapter import OpenCodeAdapter
    return {a.name: a for a in (DockerAdapter(), ClaudeCodeAdapter(), CodexAdapter(), OpenCodeAdapter(), AgyAdapter(),
                                GitHubAdapter())}
