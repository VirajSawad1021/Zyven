"""zyven verify --connection: a server connected on the board, checked with its stored credentials."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from zyven.connections.store import ConnectionStore
from zyven.mcpverify import verify_connection

FIX = Path(__file__).parent / "fixtures" / "mcp_servers"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_STDIO_CONNECTORS", "1")
    store = ConnectionStore(tmp_path)
    store.add(name="Calc", kind="stdio", command=sys.executable, args=[str(FIX / "good.py")],
              secrets={"CALC_TOKEN": "sk-very-secret-value-123"})
    store.add(name="Notes", kind="stdio", command=sys.executable, args=[str(FIX / "poisoned.py")])
    return tmp_path


def test_a_connection_is_checked_by_name_with_its_secrets(board):
    r = verify_connection(board, "calc")
    assert r.verdict == "PASS" and r.tools == ["add"]
    assert r.launch["command"][-1].endswith("good.py")
    assert verify_connection(board, "Notes").verdict == "FAIL"


def test_unknown_or_signed_out_connections_say_what_to_do(board):
    with pytest.raises(ValueError, match="connected: Calc, Notes"):
        verify_connection(board, "nope")
    store = ConnectionStore(board)
    store.add(name="Docs", kind="http", url="https://mcp.example.com/mcp", oauth=True)
    with pytest.raises(ValueError, match="not signed in"):
        verify_connection(board, "Docs")


def test_cli_never_prints_the_secret(board):
    p = subprocess.run([sys.executable, "-m", "zyven.cli", "verify", "--connection", "Calc", "--board-dir", str(board)],
                       capture_output=True, text=True, cwd=ROOT,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8", "ZYVEN_ALLOW_STDIO_CONNECTORS": "1"})
    assert p.returncode == 0, p.stdout + p.stderr
    assert "verdict: PASS" in p.stdout and "sk-very-secret" not in p.stdout + p.stderr


def test_a_hosted_server_is_not_said_to_run_on_this_machine():
    from zyven.mcpverify.checks import SKIP, WARN, run_checks
    tool = {"name": "add", "description": "Add.", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}
    base = {"target": "t", "started": True, "server": {"name": "s"}, "tools": [tool], "tools_again": [tool]}
    hosted = run_checks({**base, "launch": {"url": "https://mcp.example.com/mcp"}})
    local = run_checks({**base, "launch": {"command": ["python", "server.py"]}})
    def iso(r):
        return next(c for c in r.checks if c.name == "isolation")
    assert iso(hosted).status == SKIP and "its own host" in iso(hosted).detail
    assert iso(local).status == WARN
