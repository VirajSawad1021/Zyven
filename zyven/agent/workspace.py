"""A working folder for the agent: write files, read them, and run commands in the Docker sandbox.

This is what lets the agent do open-ended work (write a program, run it, fix it) instead of only calling
verified library tools. Each task gets its own folder. Commands run in the same locked-down container the
skills use (non-root, read-only root filesystem, capabilities dropped, memory and process limits) with the
folder mounted read-write at /work and **no network**. A command that needs the network (installing a package,
downloading something) is a separate tool that waits for the user's approval before every call.

Packages installed with `pip install --target /work/.pkgs <name>` are importable because PYTHONPATH includes it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from zyven.agent.mcp_tools import Gate, ToolBox
from zyven.sandbox.runner import DEFAULT_IMAGE, SandboxPolicy, run

MAX_FILE_CHARS = 200_000
MAX_FILES = 300
MAX_OUTPUT_CHARS = 6000
COMMAND_TIMEOUT_S = 120
NETWORK_TIMEOUT_S = 600

Runner = Callable[..., Any]


def safe_path(root: Path, rel: str) -> Path:
    """A path inside the workspace, or a ValueError the model can read and correct."""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("give a file path relative to the workspace, for example src/main.py")
    p = Path(rel.replace("\\", "/"))
    # a Windows drive path (C:\x) is refused on every system, not only where it would be absolute
    if p.is_absolute() or p.drive or ".." in p.parts or rel.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", rel.strip()):
        raise ValueError(f"{rel!r} is outside the workspace. Use a relative path such as src/main.py")
    target = (root / p).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"{rel!r} is outside the workspace")
    return target


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + f"\n...[{len(text) - MAX_OUTPUT_CHARS} more characters cut]"


class Workspace:
    def __init__(self, root: Path, runner: Runner = run, image: str = DEFAULT_IMAGE) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._run, self.image = runner, image

    # --- files ----------------------------------------------------------------------------------------
    def files(self) -> list[str]:
        out = [p.relative_to(self.root).as_posix() for p in sorted(self.root.rglob("*"))
               if p.is_file() and ".pkgs" not in p.relative_to(self.root).parts]
        return out[:MAX_FILES]

    def list_files(self, _: dict[str, Any]) -> str:
        names = self.files()
        return "\n".join(f"{n} ({(self.root / n).stat().st_size} bytes)" for n in names) or "(the workspace is empty)"

    def read_file(self, args: dict[str, Any]) -> str:
        p = safe_path(self.root, args.get("path", ""))
        if not p.is_file():
            raise ValueError(f"no such file: {args.get('path')}. Use list_files to see what exists.")
        return _clip(p.read_text(encoding="utf-8", errors="replace"))

    def write_file(self, args: dict[str, Any]) -> str:
        p = safe_path(self.root, args.get("path", ""))
        content = args.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content must be text")
        if len(content) > MAX_FILE_CHARS:
            raise ValueError(f"file too large ({len(content)} characters; the limit is {MAX_FILE_CHARS})")
        if not p.exists() and len(self.files()) >= MAX_FILES:
            raise ValueError(f"too many files (limit {MAX_FILES})")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8"))  # exact bytes: no CRLF conversion on Windows (scripts run on Linux)
        return f"wrote {args['path']} ({len(content)} characters)"

    # --- commands ---------------------------------------------------------------------------------------
    def _command(self, args: dict[str, Any], network: bool) -> str:
        cmd = args.get("command", "")
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("give the shell command to run, for example: python main.py")
        policy = SandboxPolicy(image=self.image, network=network, memory="2g", cpus="2", pids_limit=256,
                               timeout_s=NETWORK_TIMEOUT_S if network else COMMAND_TIMEOUT_S,
                               extra_env={"PYTHONPATH": "/work/.pkgs", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        res = self._run(["sh", "-c", cmd], {self.root: "/work:rw"}, policy, workdir="/work")
        head = "timed out" if getattr(res, "timed_out", False) else f"exit code {res.exit_code}"
        return f"{head}\n--- stdout ---\n{_clip(res.stdout)}\n--- stderr ---\n{_clip(res.stderr)}"

    def run_command(self, args: dict[str, Any]) -> str:
        return self._command(args, network=False)

    def run_command_with_network(self, args: dict[str, Any]) -> str:
        return self._command(args, network=True)


_PATH = {"type": "object", "properties": {"path": {"type": "string", "description": "relative path, e.g. src/main.py"}},
         "required": ["path"]}
_CMD = {"type": "object", "properties": {"command": {"type": "string", "description": "shell command, e.g. python main.py"}},
        "required": ["command"]}


def attach(tb: ToolBox, ws: Workspace, network_gate: Gate | None) -> list[str]:
    """Give the toolbox the workspace tools. Without a gate the network tool is not offered at all."""
    tb.add_native("list_files", "List the files in your working folder.", {"type": "object", "properties": {}}, ws.list_files)
    tb.add_native("read_file", "Read a text file from your working folder.", _PATH, ws.read_file)
    tb.add_native("write_file", "Create or overwrite a text file in your working folder. Use this to write code.",
                  {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                   "required": ["path", "content"]}, ws.write_file)
    tb.add_native("run_command", "Run a shell command in a sandbox with your working folder at /work. No network. "
                  "Python 3.12 with the standard library is available. Use it to run and test the code you wrote.",
                  _CMD, ws.run_command)
    names = ["list_files", "read_file", "write_file", "run_command"]
    if network_gate is not None:
        tb.add_native("run_command_with_network",
                      "Like run_command but WITH internet access, for installing packages "
                      "(pip install --target /work/.pkgs <name>) or downloading data. The user must approve each call.",
                      _CMD, ws.run_command_with_network, gate=network_gate)
        names.append("run_command_with_network")
    return names
