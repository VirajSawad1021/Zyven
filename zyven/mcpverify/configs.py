"""Read the MCP servers a client is configured with, so `zyven verify --config` can check all of them.

Formats:
  * JSON with an "mcpServers" object: Claude Desktop, Claude Code (.mcp.json, ~/.claude.json), Cursor, Windsurf, ...
    {"mcpServers": {"name": {"command": "npx", "args": [...], "env": {...}}, "web": {"url": "https://..."}}}
  * VS Code's mcp.json: {"servers": {"name": {...}}} (same entries, "type": "stdio" | "http")
  * Codex's config.toml: [mcp_servers.name] command / args / env, or url

The env values in these files are usually secrets. They are handed to the server they belong to (it needs them) and
are never printed or written to a report.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerEntry:
    name: str
    source: str
    command: list[str] = field(default_factory=list)
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    disabled: bool = False


def _entry(name: str, spec: dict, source: str) -> ServerEntry | None:
    if not isinstance(spec, dict):
        return None
    url = spec.get("url") or spec.get("serverUrl") or ""
    cmd = spec.get("command") or ""
    args = [str(a) for a in spec.get("args") or []]
    env = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    headers = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
    if not url and not cmd:
        return None
    return ServerEntry(name, source, [cmd, *args] if cmd else [], url, env, headers,
                       bool(spec.get("disabled") or spec.get("enabled") is False))


def read_config(path: Path) -> list[ServerEntry]:
    text = path.read_text(encoding="utf-8")
    out: list[ServerEntry] = []
    if path.suffix == ".toml":
        import tomllib
        data = tomllib.loads(text)
        for name, spec in (data.get("mcp_servers") or {}).items():
            e = _entry(name, spec, str(path))
            if e:
                out.append(e)
        return out
    data = json.loads(text)
    blocks = [data.get("mcpServers"), data.get("servers")]
    # ~/.claude.json keeps per-project servers under projects.<path>.mcpServers too
    for proj in (data.get("projects") or {}).values() if isinstance(data.get("projects"), dict) else []:
        if isinstance(proj, dict):
            blocks.append(proj.get("mcpServers"))
    seen: set[tuple] = set()
    for block in blocks:
        for name, spec in (block or {}).items() if isinstance(block, dict) else []:
            e = _entry(name, spec, str(path))
            if e and (key := (e.name, tuple(e.command), e.url)) not in seen:
                seen.add(key)
                out.append(e)
    return out


def known_locations() -> list[Path]:
    """Where common MCP clients keep their server lists on this machine (existing files only)."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    cands = [
        home / ".claude.json", Path(".mcp.json"),                                   # Claude Code
        home / ".cursor" / "mcp.json", Path(".cursor") / "mcp.json",                # Cursor
        home / ".codeium" / "windsurf" / "mcp_config.json",                         # Windsurf
        home / ".codex" / "config.toml",                                            # Codex
        Path(".vscode") / "mcp.json",                                               # VS Code (workspace)
        home / ".gemini" / "settings.json",                                          # Gemini CLI
    ]
    if sys.platform == "win32":
        cands.append(appdata / "Claude" / "claude_desktop_config.json")
    elif sys.platform == "darwin":
        cands.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        cands.append(home / ".config" / "Claude" / "claude_desktop_config.json")
    return [p for p in cands if p.is_file()]
