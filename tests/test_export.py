"""zyven export: a verified skill as a standalone MCP server folder."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from zyven.export import _pip_source, export

ROOT = Path(__file__).resolve().parents[1]


def test_export_of_the_committed_skill(tmp_path):
    out = export(ROOT / "skills" / "graph_algorithms", tmp_path / "g")
    names = {p.name for p in out.iterdir()}
    assert {"server.py", "pyproject.toml", "Dockerfile", "README.md", "validation-report.json", "provenance.json"} <= names
    deps = tomllib.loads((out / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    commit = json.loads((ROOT / "skills/graph_algorithms/provenance.json").read_text(encoding="utf-8"))["commit"]
    assert any(d.startswith("networkx @ git+https://github.com/networkx/networkx@" + commit) for d in deps)
    assert "def main()" in (out / "server.py").read_text(encoding="utf-8")
    docker = (out / "Dockerfile").read_text(encoding="utf-8")
    assert "USER 1000" in docker and commit in docker and "--network none" in docker
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "differential" in readme and "claude mcp add graph_algorithms" in readme


def test_only_verified_skills_are_exported(tmp_path):
    src = tmp_path / "s"
    src.mkdir()
    for f in ("server.py", "provenance.json", "capability.json"):
        (src / f).write_text("{}" if f.endswith(".json") else "", encoding="utf-8")
    (src / "validation-report.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="did not pass"):
        export(src, tmp_path / "out")


def test_a_package_in_a_subfolder_gets_a_pip_subdirectory(tmp_path):
    repo = tmp_path / "python-phonenumbers"
    (repo / "python").mkdir(parents=True)
    (repo / "python" / "setup.py").write_text("", encoding="utf-8")  # the root has no build file
    prov = {"repository": "https://github.com/daviddrysdale/python-phonenumbers", "commit": "abc",
            "source_checkout": str(repo / "python"), "source_root": "python"}
    assert _pip_source(prov)[0].endswith("@abc#subdirectory=python")
    (repo / "pyproject.toml").write_text("", encoding="utf-8")  # a src-style layout with a root build file: none
    assert "#subdirectory" not in _pip_source(prov)[0]
