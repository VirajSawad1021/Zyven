"""`zyven mcp`: the verified-skill server any coding agent can start over stdio (no board running)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from zyven.mcpverify import format_report, verify_server

ROOT = Path(__file__).resolve().parents[1]


def test_zyven_mcp_starts_from_anywhere_and_passes_zyven_verify(tmp_path):
    (tmp_path / "library").mkdir()
    env = {"PYTHONPATH": str(ROOT)}  # an installed zyven needs nothing; the test runs from a checkout
    r = verify_server([sys.executable, "-m", "zyven.cli", "mcp", "--board-dir", str(tmp_path)], env=env, probe=True)
    assert r.verdict == "PASS", format_report(r, verbose=True)
    assert r.tools == ["zyven_status"]  # an empty library still answers, and says how to add skills
    assert r.server.get("name") == "zyven"


def test_print_config_names_both_agents_and_an_absolute_board(tmp_path):
    out = subprocess.run([sys.executable, "-m", "zyven.cli", "mcp", "--board-dir", str(tmp_path), "--print-config"],
                         capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"}).stdout
    assert "claude mcp add" in out and "codex mcp add" in out and str(tmp_path.resolve()) in out
