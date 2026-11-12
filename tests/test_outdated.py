"""zyven outdated: compare a skill's verified commit with upstream, against real local git repositories."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from zyven.outdated import check, skill_dirs


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


def head(cwd) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()


def _setup(tmp_path):
    up = tmp_path / "upstream"
    (up / "lib").mkdir(parents=True)
    (up / "lib" / "core.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (up / "lib" / "other.py").write_text("x = 1\n", encoding="utf-8")
    git("init", "-q", "-b", "main", cwd=up)
    git("add", ".", cwd=up)
    git("commit", "-q", "-m", "a", cwd=up)
    pinned = head(up)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", up.as_uri(), str(checkout)], check=True, capture_output=True)
    skill = tmp_path / "library" / "lib_tools"
    skill.mkdir(parents=True)
    (skill / "provenance.json").write_text(json.dumps({"repository": up.as_uri(), "commit": pinned,
                                                       "source_checkout": str(checkout), "source_root": "."}),
                                           encoding="utf-8")
    (skill / "capability.json").write_text(json.dumps({"included_symbols": ["lib.core.f"]}), encoding="utf-8")
    return up, skill


def test_a_skill_at_upstream_head_is_up_to_date(tmp_path):
    _, skill = _setup(tmp_path)
    assert check(skill).state == "up to date"


def test_a_moved_upstream_is_reported_with_the_files_the_skill_uses(tmp_path):
    up, skill = _setup(tmp_path)
    (up / "lib" / "core.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    (up / "lib" / "other.py").write_text("x = 2\n", encoding="utf-8")
    git("commit", "-q", "-am", "b", cwd=up)
    quick = check(skill)
    assert quick.state == "behind" and quick.behind is None and quick.upstream == head(up)
    full = check(skill, fetch=True)
    assert full.behind == 1 and full.touched == ["lib/core.py"]  # other.py changed too, but the skill does not use it
    assert "2 files changed upstream, 1 in modules this skill uses" in full.detail


def test_a_skill_without_a_repository_url_is_unknown(tmp_path):
    d = tmp_path / "s"
    d.mkdir()
    (d / "provenance.json").write_text(json.dumps({"repository": "local-folder", "commit": "abc"}), encoding="utf-8")
    assert check(d).state == "unknown"
    assert skill_dirs([tmp_path]) == [d] and skill_dirs([d]) == [d]


def test_the_committed_skill_is_found():
    root = Path(__file__).resolve().parents[1]
    assert any(p.name == "graph_algorithms" for p in skill_dirs([root / "skills"]))
