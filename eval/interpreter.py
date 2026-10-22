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
    """Resolve importable packages from the active environment to their package directories.

    Only real package directories installed in site-packages are accepted. Built-in/frozen
    modules and single-file modules have no safe directory to mount: their parent could be the
    repository root (including `.env`) or all of site-packages.
    """
    paths = []
    for name in names:
        if not name.isidentifier():
            raise RuntimeError(f"invalid package name {name!r}; use a top-level package name")
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin or spec.origin in ("built-in", "frozen"):
            raise RuntimeError(f"cannot find importable package {name!r}")
        origin = Path(spec.origin)
        if not origin.is_absolute() or not origin.is_file() or origin.name != "__init__.py":
            raise RuntimeError(f"{name!r} is not an importable package directory")
        package = origin.resolve().parent
        if package.name != name:
            raise RuntimeError(f"cannot resolve {name!r} to a package directory")
        if not any(part in ("site-packages", "dist-packages") for part in package.parts):
            raise RuntimeError(f"{name!r} is not installed in site-packages")
        paths.append(package)
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
            description += (" Only the Python standard library and packages baked into the sandbox image are available; "
                            "the suite libraries are not installed and packages cannot be installed.")
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
        if not isinstance(arguments, dict):
            return False, f"run_python expects an object with a 'code' key, got {type(arguments).__name__}."
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

        try:
            result = runner.run(["python", "-c", code], mounts, policy, workdir="/tmp", max_output=MAX_OUTPUT + 1)
        except OSError as exc:
            return False, f"sandbox unavailable: {exc}"
        parts = [p for p in (result.stdout, result.stderr) if p]
        text = "\n".join(parts).strip()
        if result.timed_out:
            text = f"timed out after {self.timeout_s}s\n{text}".strip()
        if not text:
            text = "(no output)"
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n...[truncated]"
        return result.ok, text
