"""Offline tests for the eval interpreter tool (no Docker, no network)."""

from __future__ import annotations

import asyncio
import sys
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import interpreter  # noqa: E402
from eval.interpreter import PythonToolBox, resolve_libraries  # noqa: E402
from zyven.sandbox.runner import SandboxResult, _read_capped  # noqa: E402


def test_read_capped_drains_but_bounds_output():
    assert _read_capped(BytesIO(b"x" * 10000), 10) == b"x" * 10
    assert _read_capped(BytesIO(b"short"), 10) == b"short"


def test_python_tool_runs_code_in_sandbox(monkeypatch):
    seen = {}

    def fake_run(command, mounts, policy, workdir, max_output=None):
        seen.update(command=command, mounts=mounts, policy=policy, workdir=workdir, max_output=max_output)
        return SandboxResult(command, 0, "42\n", "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print(42)"}))

    assert ok and out == "42"
    assert seen["command"] == ["python", "-c", "print(42)"]
    assert seen["policy"].network is False
    assert seen["policy"].timeout_s == 30
    assert seen["mounts"] == {}
    assert seen["workdir"] == "/tmp"
    assert seen["max_output"] == 6001


def test_python_tool_mounts_only_requested_library(monkeypatch, tmp_path):
    lib = tmp_path / "mylib"
    lib.mkdir()
    (lib / "__init__.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_run(command, mounts, policy, workdir, max_output=None):
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
    ok, out = asyncio.run(tb.call("run_python", []))
    assert not ok and "object" in out


def test_resolve_libraries_rejects_builtins_and_missing_packages():
    with pytest.raises(RuntimeError):
        resolve_libraries(["math"])
    with pytest.raises(RuntimeError):
        resolve_libraries(["definitely_not_a_real_package"])
    paths = resolve_libraries(["nepali"])
    assert paths[0].name == "nepali" and paths[0].is_absolute()


def test_python_tool_reports_docker_errors(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("daemon unavailable")

    monkeypatch.setattr(interpreter.runner, "run", fail)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print(1)"}))
    assert not ok and "sandbox unavailable" in out


def test_python_tool_truncates_large_output(monkeypatch):
    def fake_run(command, mounts, policy, workdir, max_output=None):
        return SandboxResult(command, 0, "x" * 7000, "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print('x')"}))

    assert ok
    assert out.endswith("...[truncated]")
    assert len(out) < 7000
