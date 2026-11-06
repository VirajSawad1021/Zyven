"""`zyven verify`: check any MCP server from the outside (schemas, tool poisoning, rug pulls, robustness)."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from zyven.mcpverify.checks import FAIL, PASS, SKIP, WARN, Report, run_checks
from zyven.mcpverify.probe import observe, server_from

__all__ = ["verify_server", "format_report", "Report"]


def verify_server(command: list[str] | None = None, url: str | None = None, headers: dict[str, str] | None = None,
                  env: dict[str, str] | None = None, docker_image: str | None = None,
                  mounts: dict[Path, str] | None = None, probe: bool = False, lock_file: Path | None = None,
                  timeout: float = 60.0) -> Report:
    _, sandboxed, label = server_from(command, url, headers, env, docker_image, mounts)
    containers: list[str] = []

    def make():  # a fresh transport (and container name) for each connection
        name = None
        if docker_image and command:
            name = f"zyven-verify-{uuid.uuid4().hex[:12]}"
            containers.append(name)
        return server_from(command, url, headers, env, docker_image, mounts, name)[0]

    try:
        obs = asyncio.run(observe(make, label, sandboxed, probe=probe, timeout=timeout))
    finally:  # a server that ignores the end of its input would otherwise keep running
        from zyven.sandbox.runner import remove_container
        for name in containers:
            remove_container(name)
    lock = None
    if lock_file and lock_file.exists():
        lock = json.loads(lock_file.read_text(encoding="utf-8")).get("tools") or {}
    return run_checks(obs, lock)


_MARK = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}


def format_report(r: Report, verbose: bool = False) -> str:
    lines = [f"zyven verify: {r.target}", ""]
    for c in r.checks:
        lines.append(f"  {_MARK[c.status]:4}  {c.name:<13} {c.detail}")
        shown = c.findings if verbose or c.status == FAIL else c.findings[:3]
        lines += [f"          - {f}" for f in shown]
        if len(shown) < len(c.findings):
            lines.append(f"          ... {len(c.findings) - len(shown)} more (use -v)")
    warns = sum(c.status == WARN for c in r.checks)
    lines += ["", f"verdict: {r.verdict}" + (f" with {warns} warning(s)" if r.verdict == PASS and warns else "")]
    return "\n".join(lines)


def write_lock(r: Report, path: Path) -> None:
    data: dict[str, Any] = {"target": r.target, "server": r.server, "tools": r.lock}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
