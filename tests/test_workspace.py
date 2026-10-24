"""The agent's working folder: path safety, file tools, sandboxed commands, and the gate on network access."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.agent.mcp_tools import ToolBox  # noqa: E402
from zyven.agent.workspace import MAX_FILE_CHARS, MAX_OUTPUT_CHARS, Workspace, attach, safe_path  # noqa: E402


class FakeRunner:
    def __init__(self, stdout="hi\n", stderr="", exit_code=0, timed_out=False) -> None:
        self.calls = []
        self.result = SimpleNamespace(stdout=stdout, stderr=stderr, exit_code=exit_code, timed_out=timed_out)

    def __call__(self, command, mounts, policy, workdir="/src"):
        self.calls.append((command, mounts, policy, workdir))
        return self.result


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../b", "~/x", "C:\\Windows\\x", "..\\x", "", "  "])
def test_paths_outside_the_workspace_are_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        safe_path(tmp_path, bad)


def test_paths_inside_are_accepted(tmp_path):
    assert safe_path(tmp_path, "src/main.py") == (tmp_path / "src" / "main.py").resolve()


def test_write_read_and_list_round_trip(tmp_path):
    ws = Workspace(tmp_path / "w", runner=FakeRunner())
    assert "(the workspace is empty)" == ws.list_files({})
    ws.write_file({"path": "src/a.py", "content": "print(1)\n"})
    ws.write_file({"path": ".pkgs/numpy/x.py", "content": "installed package: not listed"})
    assert ws.read_file({"path": "src/a.py"}) == "print(1)\n"
    assert ws.list_files({}).splitlines() == ["src/a.py (9 bytes)"]
    with pytest.raises(ValueError, match="no such file"):
        ws.read_file({"path": "nope.txt"})
    with pytest.raises(ValueError, match="too large"):
        ws.write_file({"path": "big.txt", "content": "x" * (MAX_FILE_CHARS + 1)})


def test_commands_run_in_the_sandbox_with_the_folder_mounted_and_no_network(tmp_path):
    runner = FakeRunner(stdout="42\n")
    ws = Workspace(tmp_path / "w", runner=runner)
    out = ws.run_command({"command": "python main.py"})
    command, mounts, policy, workdir = runner.calls[0]
    assert command == ["sh", "-c", "python main.py"] and workdir == "/work"
    assert mounts == {ws.root: "/work:rw"} and policy.network is False
    assert out.startswith("exit code 0") and "42" in out
    assert policy.extra_env["PYTHONPATH"] == "/work/.pkgs"


def test_timeouts_failures_and_long_output_are_reported_plainly(tmp_path):
    assert Workspace(tmp_path / "a", runner=FakeRunner(timed_out=True)).run_command({"command": "x"}).startswith("timed out")
    assert Workspace(tmp_path / "b", runner=FakeRunner(exit_code=3, stderr="boom")).run_command({"command": "x"}).startswith("exit code 3")
    long = Workspace(tmp_path / "c", runner=FakeRunner(stdout="y" * (MAX_OUTPUT_CHARS + 500))).run_command({"command": "x"})
    assert "more characters cut" in long
    with pytest.raises(ValueError, match="shell command"):
        Workspace(tmp_path / "d", runner=FakeRunner()).run_command({"command": " "})


def test_the_network_tool_is_only_offered_with_a_gate_and_asks_before_every_call(tmp_path):
    runner = FakeRunner()
    ws = Workspace(tmp_path / "w", runner=runner)
    questions = []

    async def deny(tool, args):
        questions.append((tool, args))
        return False

    async def allow(tool, args):
        return True

    async def go():
        async with ToolBox() as plain:
            assert "run_command_with_network" not in attach(plain, ws, None)
        async with ToolBox() as tb:
            assert "run_command_with_network" in attach(tb, ws, deny)
            ok, out = await tb.call("run_command_with_network", {"command": "pip install --target /work/.pkgs numpy"})
            assert not ok and out.startswith("Denied") and runner.calls == []  # never reached the sandbox
            assert questions == [("run_command_with_network", {"command": "pip install --target /work/.pkgs numpy"})]
            ok, _ = await tb.call("run_command", {"command": "echo hi"})  # no network: no question
            assert ok and len(questions) == 1 and runner.calls[0][2].network is False
        async with ToolBox() as tb2:
            attach(tb2, ws, allow)
            ok, out = await tb2.call("run_command_with_network", {"command": "pip install x"})
            assert ok and runner.calls[-1][2].network is True

    asyncio.run(go())


def test_a_bad_call_is_returned_to_the_model_as_text_not_raised(tmp_path):
    async def go():
        async with ToolBox() as tb:
            attach(tb, Workspace(tmp_path / "w", runner=FakeRunner()), None)
            ok, out = await tb.call("write_file", {"path": "../escape.txt", "content": "x"})
            assert not ok and "outside the workspace" in out
            assert not (tmp_path / "escape.txt").exists()
            ok, out = await tb.call("write_file", {"path": "ok.txt", "content": "hello"})
            assert ok and "wrote ok.txt" in out

    asyncio.run(go())


@pytest.mark.skipif(os.environ.get("ZYVEN_DOCKER_TESTS") != "1", reason="set ZYVEN_DOCKER_TESTS=1")
def test_real_sandbox_runs_code_the_agent_wrote_and_has_no_network(tmp_path):
    ws = Workspace(tmp_path / "w")
    ws.write_file({"path": "main.py", "content": "squares = [n * n for n in range(1, 6)]\n"
                                                  "open('out.txt', 'w').write(str(squares))\nprint(squares)\n"})
    out = ws.run_command({"command": "python main.py"})
    assert out.startswith("exit code 0") and "[1, 4, 9, 16, 25]" in out
    assert ws.read_file({"path": "out.txt"}) == "[1, 4, 9, 16, 25]"  # written by the container, visible to the agent
    net = ws.run_command({"command": "python -c \"import urllib.request as u; u.urlopen('https://example.com', timeout=5)\""})
    assert not net.startswith("exit code 0")  # no network
