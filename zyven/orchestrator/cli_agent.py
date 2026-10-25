"""Shared machinery for command-line coding agents run headless from the Control center.

OpenCode, Codex, Claude Code and Antigravity are all "a program that takes a prompt, works in a folder, and prints
events". What they share, and what Zyven therefore does the same way for each:

  * the prompt goes on stdin where the program supports it, so nothing the user typed touches a shell;
  * the child's working folder is pinned to the task folder, including $PWD (OpenCode trusts $PWD over the real
    working directory; a live test caught it writing into the wrong folder and ignoring its permission file);
  * stderr is read separately, so a program's log lines never get mixed into its JSON event stream;
  * a repository that ships its own agent settings (hooks, permissions) is refused, because those settings run
    with the agent's powers;
  * cancel and the time limit kill the whole process tree;
  * each adapter reports whether its program is installed and signed in, for the dashboard.

Each program is off unless its ZYVEN_ENABLE_* variable is 1: the task text goes to whichever provider that program
is signed in to. Zyven does not claim these runs are open-weight; the model is the user's choice.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from zyven.orchestrator import settings
from zyven.orchestrator.adapters import RUN_TIMEOUT_S, RunContext, RuntimeAdapter, kill_tree

STATUS_TTL_S = 60
DEFAULT_IDLE_S = 300  # a program that prints nothing for this long is stuck (for example waiting on a permission)


def run_quiet(cmd: list[str], timeout: float = 15) -> str:
    """Output of a short status command (stdout and stderr), or '' if it fails or times out."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
        return (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


class CLIAgentAdapter(RuntimeAdapter):
    binary = ""                       # program name looked up on PATH
    env_flag = ""                     # e.g. ZYVEN_ENABLE_CODEX
    privacy = "the task text goes to the provider this program is signed in to"
    stdin_prompt = True               # False: the prompt is passed as an argument (a native program, never via a shell)
    project_config_dirs: tuple[str, ...] = ()
    sign_in_help = ""
    idle_timeout_s: float | None = DEFAULT_IDLE_S

    def __init__(self, executable: list[str] | None = None) -> None:
        self._exe = executable        # tests point this at a stand-in program
        self._procs: dict[str, subprocess.Popen] = {}
        self._status: tuple[float, dict[str, Any]] | None = None
        self._refreshing = threading.Event()

    # --- what a subclass provides ---------------------------------------------------------------------
    def command(self, cwd: Path | None = None, full: bool = False) -> list[str]:
        raise NotImplementedError

    def prepare(self, ctx: RunContext) -> str:
        """Write settings into the task folder before the program starts. Returns a line for the log."""
        return ""

    def parse(self, line: str, emit: Callable[[str, str], None], totals: dict[str, float]) -> bool:
        """Turn one output line into run events and token totals. True when the line reports an error."""
        raise NotImplementedError

    def sign_in_state(self) -> tuple[bool | None, str]:
        """(signed in?, detail). None means the program cannot say."""
        return None, ""

    # --- shared behaviour -------------------------------------------------------------------------------
    def model(self) -> str:
        """The model chosen on the Control center page, else ZYVEN_<NAME>_MODEL, else '' (the program's own default)."""
        value = settings.model_for(self.name)
        if value and not settings.MODEL.fullmatch(value):
            raise ValueError(f"the {self.label} model looks wrong: {value!r}")
        return value

    def _executable(self) -> list[str] | None:
        if self._exe:
            return self._exe
        found = shutil.which(self.binary)
        return [found] if found else None

    def available(self) -> tuple[bool, str]:
        if not settings.is_enabled(self.name, self.env_flag):
            return False, f"Off by default: {self.privacy}. Switch it on in the Control center (or set {self.env_flag}=1)."
        if not self._executable():
            return False, f"`{self.binary}` is not on PATH. {self.sign_in_help}"
        return True, ""

    def _check(self) -> dict[str, Any]:
        installed = bool(self._executable())
        signed_in, detail = self.sign_in_state() if installed else (None, "")
        if not installed:
            detail = f"`{self.binary}` is not installed. {self.sign_in_help}"
        elif signed_in is False:
            detail = detail or f"Not signed in. {self.sign_in_help}"
        out = {"installed": installed, "signed_in": signed_in, "detail": detail}
        self._status = (time.monotonic(), out)
        return out

    def status(self, wait: bool = False) -> dict[str, Any]:
        """Installed and signed in? Asking the program takes seconds, so the answer is cached for a minute and
        refreshed in the background: a page load gets the last known answer (or 'checking') at once."""
        if self._status and time.monotonic() - self._status[0] < STATUS_TTL_S:
            return self._status[1]
        if wait:
            return self._check()
        if not self._refreshing.is_set():
            self._refreshing.set()

            def refresh() -> None:
                try:
                    self._check()
                finally:
                    self._refreshing.clear()

            threading.Thread(target=refresh, daemon=True).start()
        if self._status:
            return self._status[1]  # stale, but better than blocking
        return {"installed": bool(self._executable()), "signed_in": None, "detail": "Checking sign-in…"}

    def info(self) -> dict[str, Any]:
        out = super().info()
        out["status"] = self.status()
        return out

    def run(self, ctx: RunContext) -> int:
        rid = ctx.run["id"]
        ctx = replace(ctx, cwd=Path(ctx.cwd).resolve(), workdir=Path(ctx.workdir).resolve())  # never a relative path
        for name in self.project_config_dirs:
            if ctx.run["repo_url"] and (ctx.cwd / name).exists():
                ctx.emit("error", f"this repository ships its own {self.label} settings ({name}); "
                                  "refusing to run it with them")
                return 2
        full = bool(ctx.run.get("full_access")) and self.supports_full_access
        note = self.prepare(ctx)
        cmd = self.command(ctx.cwd, full)
        if full:
            ctx.emit("error", "FULL PC ACCESS: this run is NOT sandboxed. It can read, change and delete any file your "
                              "account can, and run any program.")
        # npm installs programs on Windows as .cmd shims, which cmd.exe parses: keep its metacharacters out of every
        # argument we choose (the prompt is exempt: it goes on stdin, or to a native program).
        if os.name == "nt" and cmd[0].lower().endswith((".cmd", ".bat")) and any(re.search(r'[&|<>^%!"]', a) for a in cmd[1:]):
            ctx.emit("error", f"refusing to start {self.label}: a path or setting contains a character cmd.exe would misread")
            return 2
        if not self.stdin_prompt:
            cmd = [*cmd, ctx.run["prompt"]]
        if note:
            ctx.emit("info", note)
        env = {**os.environ, "PWD": str(ctx.cwd)}  # see the module note: a parent shell's PWD must not leak in
        env.pop("OLDPWD", None)
        p = subprocess.Popen(cmd, cwd=ctx.cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        self._procs[rid] = p
        killer = threading.Timer(RUN_TIMEOUT_S, lambda: self.cancel(rid))
        killer.start()
        totals = {"in": 0, "out": 0, "cost": 0.0}
        failed = False
        assert p.stdin is not None and p.stdout is not None and p.stderr is not None
        last_output = [time.monotonic()]
        stalled = threading.Event()

        def watchdog() -> None:
            while p.poll() is None:
                time.sleep(1)
                if self.idle_timeout_s and time.monotonic() - last_output[0] > self.idle_timeout_s:
                    stalled.set()
                    ctx.emit("error", f"{self.label} printed nothing for {int(self.idle_timeout_s)}s and was stopped "
                                      "(it may be waiting for a permission nobody can give in headless mode)")
                    kill_tree(p)
                    return

        def drain_stderr() -> None:  # a program's own log lines: shown as info, never parsed as events
            for line in p.stderr:  # type: ignore[union-attr]
                last_output[0] = time.monotonic()
                if line.strip():
                    ctx.emit("info", line.strip()[:300])

        threading.Thread(target=watchdog, daemon=True).start()

        err_thread = threading.Thread(target=drain_stderr, daemon=True)
        err_thread.start()
        try:
            try:
                if self.stdin_prompt:
                    p.stdin.write(ctx.run["prompt"])
                p.stdin.close()
            except OSError:
                pass  # the program exited before reading its input: its output explains why
            for line in p.stdout:
                last_output[0] = time.monotonic()
                failed = self.parse(line, ctx.emit, totals) or failed
            code = p.wait()
            err_thread.join(2)
            ctx.emit("info", f"done: {int(totals['in'])} in / {int(totals['out'])} out tokens"
                             + (f", ${totals['cost']:.4f}" if totals["cost"] else ""))
            return code or (1 if failed or stalled.is_set() else 0)
        finally:
            killer.cancel()
            self._procs.pop(rid, None)

    def cancel(self, run_id: str) -> None:
        p = self._procs.get(run_id)
        if p and p.poll() is None:
            kill_tree(p)
