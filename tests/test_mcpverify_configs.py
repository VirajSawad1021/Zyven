"""zyven verify --config: read client configs and check every server in them."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from zyven.mcpverify.configs import read_config

FIX = Path(__file__).parent / "fixtures" / "mcp_servers"
ROOT = Path(__file__).resolve().parents[1]


def test_claude_desktop_cursor_style(tmp_path):
    f = tmp_path / "claude_desktop_config.json"
    f.write_text(json.dumps({"mcpServers": {
        "files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"], "env": {"K": "v"}},
        "web": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer x"}},
        "off": {"command": "x", "disabled": True},
        "broken": {"args": ["no command"]}}}), encoding="utf-8")
    es = {e.name: e for e in read_config(f)}
    assert set(es) == {"files", "web", "off"}  # an entry without a command or url is ignored
    assert es["files"].command[:2] == ["npx", "-y"] and es["files"].env == {"K": "v"}
    assert es["web"].url and es["web"].headers["Authorization"] == "Bearer x" and es["off"].disabled


def test_vscode_and_claude_code_project_blocks(tmp_path):
    vs = tmp_path / "mcp.json"
    vs.write_text(json.dumps({"servers": {"a": {"type": "stdio", "command": "node", "args": ["a.js"]}}}), encoding="utf-8")
    assert [e.name for e in read_config(vs)] == ["a"]
    cc = tmp_path / ".claude.json"
    cc.write_text(json.dumps({"mcpServers": {"g": {"command": "g"}},
                              "projects": {"/p": {"mcpServers": {"p": {"command": "p"}, "g": {"command": "g"}}}}}),
                  encoding="utf-8")
    assert sorted(e.name for e in read_config(cc)) == ["g", "p"]  # the duplicate 'g' is checked once


def test_codex_toml(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('model = "x"\n[mcp_servers.docs]\ncommand = "uvx"\nargs = ["docs-mcp"]\n'
                 '[mcp_servers.docs.env]\nTOKEN = "t"\n[mcp_servers.remote]\nurl = "https://r.example/mcp"\n',
                 encoding="utf-8")
    es = {e.name: e for e in read_config(f)}
    assert es["docs"].command == ["uvx", "docs-mcp"] and es["docs"].env == {"TOKEN": "t"} and es["remote"].url


def test_a_key_in_a_url_never_reaches_the_label():
    from zyven.mcpverify.probe import server_from
    _, _, label = server_from(None, "https://user:pw@mcp.example.com:8443/mcp?api_key=sk-123&x=1")
    assert label == "https://mcp.example.com:8443/mcp?…" and "sk-123" not in label and "pw" not in label


def test_verify_config_checks_every_server_and_never_prints_env_values(tmp_path):
    secret = "sk-very-secret-value-123"
    f = tmp_path / "mcp.json"
    f.write_text(json.dumps({"mcpServers": {
        "calc": {"command": sys.executable, "args": [str(FIX / "good.py")], "env": {"CALC_TOKEN": secret}},
        "notes": {"command": sys.executable, "args": [str(FIX / "poisoned.py")]},
        "old": {"command": sys.executable, "args": ["x.py"], "disabled": True}}}), encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "zyven.cli", "verify", "--config", str(f), "--json", str(tmp_path / "r.json")],
                       capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert p.returncode == 1, p.stdout + p.stderr  # one server fails
    assert "PASS  calc" in p.stdout and "FAIL  notes" in p.stdout and "skipped" in p.stdout
    assert secret not in p.stdout + p.stderr + (tmp_path / "r.json").read_text(encoding="utf-8")
    assert {r["name"]: r["verdict"] for r in json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))} == \
        {"calc": "PASS", "notes": "FAIL"}
