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
