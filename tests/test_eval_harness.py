"""Offline tests for the eval interpreter tool (no Docker, no network)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import interpreter  # noqa: E402
from eval.interpreter import PythonToolBox  # noqa: E402
from zyven.sandbox.runner import SandboxResult  # noqa: E402


def test_python_tool_runs_code_in_sandbox(monkeypatch):
    seen = {}

    def fake_run(command, mounts, policy, workdir):
        seen.update(command=command, mounts=mounts, policy=policy, workdir=workdir)
        return SandboxResult(command, 0, "42\n", "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print(42)"}))

    assert ok and out == "42"
    assert seen["command"] == ["python", "-c", "print(42)"]
    assert seen["policy"].network is False
    assert seen["policy"].timeout_s == 30
    assert seen["mounts"] == {}
    assert seen["workdir"] == "/tmp"


def test_python_tool_mounts_only_requested_library(monkeypatch, tmp_path):
    lib = tmp_path / "mylib"
    lib.mkdir()
    (lib / "__init__.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_run(command, mounts, policy, workdir):
        seen.update(mounts=mounts, policy=policy)
        return SandboxResult(command, 0, "", "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    tb = PythonToolBox([lib], ["mylib"])
    ok, _ = asyncio.run(tb.call("run_python", {"code": "import mylib"}))

    assert ok
    assert seen["mounts"] == {lib: "/libs/0/mylib"}
    assert seen["policy"].extra_env["PYTHONPATH"] == "/libs/0"
    assert "mylib" in tb.openai_tools[0]["function"]["description"]


def test_python_tool_rejects_bad_input():
    tb = PythonToolBox()
    assert asyncio.run(tb.call("other", {}))[0] is False
    ok, out = asyncio.run(tb.call("run_python", {"code": "  "}))
    assert not ok and "non-empty" in out


def test_python_tool_truncates_large_output(monkeypatch):
    def fake_run(command, mounts, policy, workdir):
        return SandboxResult(command, 0, "x" * 7000, "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print('x')"}))

    assert ok
    assert out.endswith("...[truncated]")
    assert len(out) < 7000
