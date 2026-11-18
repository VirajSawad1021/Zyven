from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from zyven.mcpverify.checks import run_checks
from zyven.mcpverify.srt import CREDENTIAL_DIRS, srt_settings

FIX = Path(__file__).parent / "fixtures" / "mcp_servers"
ROOT = Path(__file__).resolve().parents[1]
ADD = {"name": "add", "description": "Add two integers.",
       "inputSchema": {"type": "object", "properties": {"a": {"type": "integer", "description": "first"},
                                                        "b": {"type": "integer", "description": "second"}},
                       "required": ["a", "b"]},
       "annotations": {"readOnlyHint": True}}


def obs(**kw):
    base = {"target": "t", "started": True, "server": {"name": "s"}, "tools": [ADD], "tools_again": [ADD], "seconds": 1}
    return {**base, **kw}


def test_reached_hosts_become_least_privilege_srt_settings():
    egress = {"hosts": ["api.example.com", "cdn.example.com"], "decisions": [
        {"host": "cdn.example.com", "port": 443, "allowed": True},
        {"host": "api.example.com", "port": 443, "allowed": True},
        {"host": "cdn.example.com", "port": 443, "allowed": True},
        {"host": "refused.example.com", "port": 443, "allowed": False},
    ]}
    settings = srt_settings(run_checks(obs(sandboxed=True, egress=egress)))
    assert set(settings) == {"filesystem", "network"}
    assert settings["network"]["allowedDomains"] == ["api.example.com", "cdn.example.com"]
    assert settings["network"]["deniedDomains"] == []
    assert settings["filesystem"]["allowWrite"] == []
    assert settings["filesystem"]["denyRead"] == CREDENTIAL_DIRS
    assert settings["filesystem"]["denyWrite"] == []


def test_no_reached_hosts_means_no_network_access():
    egress = {"hosts": ["api.example.com"], "decisions": []}
    settings = srt_settings(run_checks(obs(sandboxed=True, egress=egress)))
    assert settings["network"]["allowedDomains"] == []


def test_settings_require_a_network_observation():
    with pytest.raises(ValueError, match="--allow-host"):
        srt_settings(run_checks(obs()))


def test_cli_without_network_observation_writes_no_settings(tmp_path):
    out = tmp_path / "srt.json"
    result = subprocess.run(
        [sys.executable, "-m", "zyven.cli", "verify", "--srt-settings", str(out), "--",
         sys.executable, str(FIX / "good.py")],
        capture_output=True, text=True, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0
    assert "srt settings not written" in result.stdout
    assert not out.exists()
