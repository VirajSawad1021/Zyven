"""GitHub connector: validation, approval gate, and the exact command (no network, no real gh)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator.control import Control  # noqa: E402
from zyven.orchestrator.github_adapter import GitHubAdapter, plan  # noqa: E402


def test_create_repo_is_private_by_default_and_builds_the_exact_command():
    kind, summary, argv = plan(json.dumps({"action": "create_repo", "name": "demo", "description": "A demo"}))
    assert kind == "github.create_repo" and "private" in summary
    assert argv == ["gh", "repo", "create", "demo", "--private", "--description", "A demo"]
    public = plan(json.dumps({"action": "create_repo", "name": "demo", "private": False}))
    assert public[2][-1] == "--public" and "PUBLIC" in public[1]


@pytest.mark.parametrize("task, msg", [
    ("not json", "JSON"),
    ("[]", "JSON object"),
    (json.dumps({"action": "delete_repo", "name": "x"}), "unknown action"),
    (json.dumps({"action": "create_repo", "name": "../evil; rm -rf"}), "valid repository name"),
    (json.dumps({"action": "create_repo", "name": "ok", "private": "no"}), "true or false"),
    (json.dumps({"action": "create_issue", "repo": "just-a-name", "title": "t"}), "owner/name"),
    (json.dumps({"action": "create_issue", "repo": "o/r", "title": "  "}), "title"),
])
def test_bad_tasks_are_rejected_before_any_approval(task, msg):
    with pytest.raises(ValueError, match=msg):
        plan(task)


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ZYVEN_ENABLE_GITHUB", raising=False)
    ok, why = GitHubAdapter().available()
    assert not ok and "ZYVEN_ENABLE_GITHUB=1" in why


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "https://github.com/me/demo\n", "")


def _run(tmp_path, task, decision):
    rec = Recorder()
    c = Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {"github": GitHubAdapter(runner=rec)}, autostart=False)
    rid = c.create(title="", runtime="github", prompt=task)["id"]
    t = threading.Thread(target=c._run_worker, args=(rid,))
    t.start()
    pending = []
    for _ in range(100):
        pending = c.approvals_for(run=rid, pending_only=True)
        if pending:
            break
        time.sleep(0.05)
    assert pending and rec.calls == []  # nothing ran before the decision
    assert "gh repo create demo --private" in pending[0]["detail"]
    c.decide(pending[0]["id"], decision)
    t.join(5)
    return c, rid, rec


def test_nothing_runs_until_approved_then_the_command_runs_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_GITHUB", "1")
    monkeypatch.setattr("shutil.which", lambda name: "gh")
    c, rid, rec = _run(tmp_path, json.dumps({"action": "create_repo", "name": "demo"}), True)
    assert rec.calls == [["gh", "repo", "create", "demo", "--private"]]
    run = c.get(rid)
    assert run["status"] == "COMPLETED" and any("github.com/me/demo" in e["text"] for e in run["log"])


def test_denied_means_gh_is_never_called(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_GITHUB", "1")
    monkeypatch.setattr("shutil.which", lambda name: "gh")
    c, rid, rec = _run(tmp_path, json.dumps({"action": "create_repo", "name": "demo"}), False)
    assert rec.calls == [] and c.get(rid)["status"] == "FAILED"
    assert any("not approved" in e["text"] for e in c.get(rid)["log"])
