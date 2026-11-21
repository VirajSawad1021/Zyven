"""A missing or stopped Docker is reported in words, not as "Connection closed"."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from zyven.sandbox import runner


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(runner, "_DOCKER_OK", set())


def _fake(results):
    def run(cmd, **kw):
        out = results[cmd[1]]
        if isinstance(out, BaseException):
            raise out
        return SimpleNamespace(returncode=out[0], stdout=out[1], stderr="")
    return run


def test_not_installed_not_running_and_no_image(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake({"info": FileNotFoundError()}))
    assert "not installed" in runner.docker_problem()
    monkeypatch.setattr(subprocess, "run", _fake({"info": (1, "")}))
    assert "not running" in runner.docker_problem()
    monkeypatch.setattr(subprocess, "run", _fake({"info": (0, "28.4.0"), "image": (1, "")}))
    assert "zyven setup" in runner.docker_problem()
    assert "pull or build" in runner.docker_problem("node:20")


def test_a_working_docker_is_checked_once(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[1])
        return SimpleNamespace(returncode=0, stdout="x", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    assert runner.docker_problem() is None and runner.docker_problem() is None
    assert calls == ["info", "image"]


def test_a_sandboxed_skill_says_docker_is_not_running(monkeypatch, tmp_path):
    from zyven.agent.mcp_tools import MCPServerSpec, ToolBox
    monkeypatch.setattr(runner, "docker_problem", lambda image=runner.DEFAULT_IMAGE: "Docker is not running; start it")
    spec = MCPServerSpec.sandboxed("graph", tmp_path)

    async def go():
        async with ToolBox() as box:
            await box.add_server(spec)
    with pytest.raises(RuntimeError, match="skill graph runs in the sandbox, but Docker is not running"):
        asyncio.run(go())
