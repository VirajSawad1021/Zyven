"""`zyven verify`: check any MCP server from the outside (schemas, tool poisoning, rug pulls, robustness)."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from zyven.mcpverify.checks import FAIL, PASS, SKIP, WARN, Report, run_checks
from zyven.mcpverify.probe import observe, server_from

__all__ = ["verify_server", "verify_connection", "format_report", "Report"]


def verify_server(command: list[str] | None = None, url: str | None = None, headers: dict[str, str] | None = None,
                  env: dict[str, str] | None = None, docker_image: str | None = None,
                  mounts: dict[Path, str] | None = None, probe: bool = False, lock_file: Path | None = None,
                  timeout: float = 60.0, network: bool = False, allow_hosts: list[str] | None = None) -> Report:
    _, sandboxed, label = server_from(command, url, headers, env, docker_image, mounts, network=network)
    if allow_hosts and not (docker_image and command):
        raise ValueError("--allow-host needs --docker and a server command: the allowlist is enforced by the sandbox")
    egress = None
    containers: list[str] = []

    def make():  # a fresh transport (and container name) for each connection
        name = None
        if docker_image and command:
            name = f"zyven-verify-{uuid.uuid4().hex[:12]}"
            containers.append(name)
        return server_from(command, url, headers, env, docker_image, mounts, name, network, egress)[0]

    try:
        if allow_hosts:
            from zyven.sandbox.egress import Egress
            egress = Egress(allow_hosts).__enter__()
        obs = asyncio.run(observe(make, label, sandboxed, probe=probe, timeout=timeout))
        obs["network"] = bool(network and docker_image)
        obs["launch"] = {"command": list(command)} if command else {"url": url}
        if docker_image:
            from zyven.mcpverify.pinning import image_id
            obs["image"] = {"name": docker_image, "id": image_id(docker_image)}
        if egress is not None:
            obs["egress"] = {"hosts": egress.hosts, "decisions": egress.decisions()}
    finally:  # a server that ignores the end of its input would otherwise keep running
        from zyven.sandbox.runner import remove_container
        for name in containers:
            remove_container(name)
        if egress is not None:
            egress.__exit__(None, None, None)
    return _checked(obs, lock_file)


def _checked(obs: dict[str, Any], lock_file: Path | None) -> Report:
    lock = locked = None
    if lock_file and lock_file.exists():
        locked = json.loads(lock_file.read_text(encoding="utf-8"))
        lock = locked.get("tools") or {}
    return run_checks(obs, lock, locked)


def verify_connection(board_dir: Path, name: str, probe: bool = False, lock_file: Path | None = None,
                      timeout: float = 60.0) -> Report:
    """Check a server connected on the board, signed in: with its stored key, or its OAuth sign-in. The tokens are
    used through the board's own store and refreshed there, never copied: a copied Notion refresh token would sign the
    board out (Notion rotates refresh tokens on use)."""
    from zyven.connections.probe import server_for
    from zyven.connections.store import ConnectionStore

    store = ConnectionStore(board_dir)
    conns = store.list()
    conn = next((c for c in conns if c["id"] == name), None) or \
        next((c for c in conns if c.get("name", "").lower() == name.lower()), None)
    if conn is None:  # "notion" for "Notion (hosted by Notion)", if only one name starts that way
        starts = [c for c in conns if c.get("name", "").lower().startswith(name.lower())]
        if len(starts) > 1:
            raise ValueError(f"{name!r} matches several connections: {', '.join(c['name'] for c in starts)}")
        conn = starts[0] if starts else None
    if conn is None:
        known = ", ".join(sorted(c.get("name", c["id"]) for c in conns)) or "none"
        raise ValueError(f"no connection {name!r} on the board in {board_dir} (connected: {known})")
    if conn.get("oauth") and not conn.get("signed_in"):
        raise ValueError(f"{conn['name']} is not signed in: open the board's Connections page and sign in first")
    where = conn.get("url") or " ".join([conn.get("command", ""), *conn.get("args", [])])
    obs = asyncio.run(observe(lambda: server_for(store, conn["id"], conn), f"{conn['name']} ({where})", False,
                              probe=probe, timeout=timeout))
    obs["launch"] = ({"url": conn["url"]} if conn.get("kind") == "http"
                     else {"command": [conn.get("command", ""), *conn.get("args", [])]})
    return _checked(obs, lock_file)


_MARK = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}


def format_report(r: Report, verbose: bool = False) -> str:
    lines = [f"zyven verify: {r.target}", ""]
    for c in r.checks:
        lines.append(f"  {_MARK[c.status]:4}  {c.name:<13} {c.detail}")
        shown = c.findings if verbose or c.status == FAIL else c.findings[:3]
        lines += [f"          - {f}" for f in shown]
        if len(shown) < len(c.findings):
            lines.append(f"          ... {len(c.findings) - len(shown)} more (use -v)")
    if r.capabilities:
        shown = r.capabilities if verbose else r.capabilities[:5]
        lines += ["", f"  capabilities: what it can do or touches ({len(r.capabilities)}; listed, not counted against it)"]
        lines += [f"          - {c}" for c in shown]
        if len(shown) < len(r.capabilities):
            lines.append(f"          ... {len(r.capabilities) - len(shown)} more (use -v)")
    warns = sum(c.status == WARN for c in r.checks)
    lines += ["", f"verdict: {r.verdict}" + (f" with {warns} warning(s)" if r.verdict == PASS and warns else "")]
    return "\n".join(lines)


_ICON = {PASS: "✅", WARN: "⚠️", FAIL: "❌", SKIP: "➖"}


def format_markdown(r: Report) -> str:
    """The report as Markdown, e.g. for a GitHub Actions job summary or a PR comment."""
    warns = sum(c.status == WARN for c in r.checks)
    head = (f"### {_ICON[r.verdict]} `zyven verify`: {r.verdict}" + (f" with {warns} warning(s)" if r.verdict == PASS and warns else ""))
    srv = " ".join(x for x in (r.server.get("name"), r.server.get("version")) if x)
    lines = [head, "", f"**Server:** {srv or r.target} · **tools:** {len(r.tools)}", "",
             "| | Check | Result |", "|---|---|---|"]
    for c in r.checks:
        lines.append(f"| {_ICON[c.status]} | {c.name} | {c.detail.replace('|', '/')} |")
    detailed = [c for c in r.checks if c.findings and c.status in (FAIL, WARN)]
    for c in detailed:
        lines += ["", f"<details{' open' if c.status == FAIL else ''}><summary><b>{c.name}</b>: {len(c.findings)} finding(s)"
                      "</summary>", ""]
        lines += [f"- `{f.replace('`', chr(39))}`" for f in c.findings[:40]]
        lines += ["", "</details>"]
    if r.capabilities:
        lines += ["", f"<details><summary><b>capabilities</b>: {len(r.capabilities)} (what it can do or touches; "
                      "not counted against it)</summary>", ""]
        lines += [f"- `{c.replace('`', chr(39))}`" for c in r.capabilities[:40]]
        lines += ["", "</details>"]
    lines += ["", "<sub>Outside-in checks by [Zyven](https://github.com/VirajSawad1021/Zyven); not a security audit.</sub>"]
    return "\n".join(lines) + "\n"


LOCK_VERSION = 2


def write_lock(r: Report, path: Path) -> None:
    """Version 2 records more than the tool definitions: the server's name and version, how it was launched (and the
    image build), and the hosts it reached through the egress proxy. Version 1 files (tools only) still work."""
    data: dict[str, Any] = {"lock_version": LOCK_VERSION, "target": r.target, "server": r.server, "launch": r.launch}
    if r.reached_hosts is not None:
        data["reached_hosts"] = r.reached_hosts
    data["tools"] = r.lock
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
