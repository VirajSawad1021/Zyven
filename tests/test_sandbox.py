"""Sandbox integration tests (need Docker and the zyven-sandbox image). Enabled with ZYVEN_DOCKER_TESTS=1."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.sandbox.runner import run, run_upstream_tests  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("ZYVEN_DOCKER_TESTS") != "1", reason="set ZYVEN_DOCKER_TESTS=1")

PY_NEPALI = ("https://github.com/opensource-nepal/py-nepali", "3ff19477150ea597d6ce2e9d3dce62e6cf0065e6")


@pytest.fixture(scope="session")
def py_nepali(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("repos") / "py-nepali"
    subprocess.run(["git", "clone", "--quiet", PY_NEPALI[0], str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "--quiet", PY_NEPALI[1]], check=True)
    d.chmod(0o755)
    return d


def test_upstream_tests_pass_in_sandbox(py_nepali):
    rep = run_upstream_tests(py_nepali, ["tests/test_date_converter.py", "tests/test_phone_number.py"])
    assert rep.passed and rep.ran == 68, rep.tail


def test_sandbox_has_no_network_and_is_not_root(tmp_path):
    tmp_path.chmod(0o755)
    r = run(["python", "-c", "import os, urllib.request\nprint('uid', os.getuid())\n"
             "urllib.request.urlopen('https://pypi.org', timeout=5)"], {tmp_path: "/src"})
    assert "uid 1000" in r.stdout
    assert r.exit_code != 0  # name resolution fails: --network none


def test_source_mount_is_read_only(py_nepali):
    r = run(["sh", "-c", "touch /src/x"], {py_nepali: "/src"})
    assert r.exit_code != 0 and "Read-only" in (r.stderr + r.stdout)


PROBE_SERVER = '''
import json, os, socket
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="probe")


def _try(fn):
    try:
        fn()
        return "allowed"
    except Exception as e:
        return "blocked: " + type(e).__name__


@server.tool(name="probe")
def probe() -> dict:
    """Reports what this server can do from inside its runtime."""
    import zyven_probe_lib  # importable only through PYTHONPATH=/src
    return {
        "uid": os.getuid(),
        "network": _try(lambda: socket.create_connection(("1.1.1.1", 53), timeout=3)),
        "write_skill": _try(lambda: open("/skill/x", "w").write("x")),
        "write_src": _try(lambda: open("/src/x", "w").write("x")),
        "write_tmp": _try(lambda: open("/tmp/x", "w").write("x")),
        "library_value": zyven_probe_lib.VALUE,
    }


if __name__ == "__main__":
    server.run("stdio")
'''


@pytest.mark.anyio
async def test_skills_run_isolated_at_runtime(tmp_path):
    """A skill launched the way the agent launches it gets the verification sandbox: no network, non-root,
    read-only skill and source mounts, only /tmp writable, and its pinned source importable."""
    import json

    from zyven.agent.mcp_tools import ToolBox
    from zyven.memory.skills import skill_server_spec

    skill, src = tmp_path / "skill", tmp_path / "src"
    skill.mkdir()
    src.mkdir()
    (skill / "server.py").write_text(PROBE_SERVER, encoding="utf-8")
    (src / "zyven_probe_lib.py").write_text("VALUE = 42\n", encoding="utf-8")
    for d in (tmp_path, skill, src):
        d.chmod(0o755)
    (skill / "server.py").chmod(0o644)
    (src / "zyven_probe_lib.py").chmod(0o644)

    async with ToolBox() as tb:
        names = await tb.add_server(skill_server_spec("probe", skill, src))
        assert names == ["probe"]
        ok, out = await tb.call("probe", {})
    assert ok, out
    r = json.loads(out)
    r = r.get("result", r)  # dict results may be wrapped, depending on the MCP version
    assert r["uid"] == 1000
    assert r["network"].startswith("blocked")
    assert r["write_skill"].startswith("blocked") and r["write_src"].startswith("blocked")
    assert r["write_tmp"] == "allowed"
    assert r["library_value"] == 42
