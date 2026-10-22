"""One sandboxed `run_python` tool for the evaluation interpreter conditions."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Any

from zyven.sandbox import runner
from zyven.sandbox.runner import DEFAULT_IMAGE, SandboxPolicy

MAX_OUTPUT = 6000


def resolve_libraries(names: list[str]) -> list[Path]:
    """Resolve importable packages from the active environment to their package directories."""
    paths = []
    for name in names:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"cannot find importable package {name!r}")
        paths.append(Path(spec.origin).parent)
    return paths


def docker_ready(image: str = DEFAULT_IMAGE) -> bool:
    """True when the Docker daemon and the sandbox image are both available."""
    if not shutil.which("docker"):
        return False
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        if info.returncode != 0:
            return False
        img = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15)
        return img.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class PythonToolBox:
    """Duck-typed toolbox: only `openai_tools` and `async call(name, args)` are used by run_agent."""

    def __init__(self, libraries: list[Path] | None = None, library_names: list[str] | None = None,
                 timeout_s: int = 30) -> None:
        self.libraries = libraries or []
        self.library_names = library_names or []
        self.timeout_s = timeout_s
        self.openai_tools = [self._tool_spec()]

    def _tool_spec(self) -> dict[str, Any]:
        description = (
            "Execute Python 3.12 code in a network-isolated sandbox and return stdout/stderr. "
            "Use print() to inspect values. The working directory is read-only; use /tmp for temporary files."
        )
        if self.library_names:
            description += " These packages are importable: " + ", ".join(self.library_names) + "."
        else:
            description += " Only the Python standard library is available; packages cannot be installed."
        return {
            "type": "function",
            "function": {
                "name": "run_python",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {"code": {"type": "string", "description": "Python source code to run."}},
                    "required": ["code"],
                },
            },
        }

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        if name != "run_python":
            return False, f"Unknown tool {name!r}. Available: run_python"
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return False, "run_python requires a non-empty string argument named 'code'."
        return await asyncio.to_thread(self._run, code)

    def _run(self, code: str) -> tuple[bool, str]:
        policy = SandboxPolicy(network=False, memory="512m", cpus="1", pids_limit=64, timeout_s=self.timeout_s)
        mounts: dict[Path, str] = {}
        search_paths = []
        for i, lib in enumerate(self.libraries):
            mounts[lib] = f"/libs/{i}/{lib.name}"
            search_paths.append(f"/libs/{i}")
        if search_paths:
            policy.extra_env["PYTHONPATH"] = ":".join(search_paths)

        result = runner.run(["python", "-c", code], mounts, policy, workdir="/tmp")
        text = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.timed_out:
            text = f"timed out after {self.timeout_s}s\n{text}".strip()
        if not text:
            text = "(no output)"
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n...[truncated]"
        return result.ok, text
