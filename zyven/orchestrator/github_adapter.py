"""GitHub connector: create a repository or an issue, behind an approval card.

The task is a small JSON object, so what will happen is explicit and auditable:

  {"action": "create_repo",  "name": "my-repo", "description": "...", "private": true}
  {"action": "create_issue", "repo": "owner/name", "title": "...", "body": "..."}

The exact `gh` command is shown on the approval card; nothing runs unless the user approves. Repositories are
private unless the task says otherwise. Off unless ZYVEN_ENABLE_GITHUB=1 and `gh` is installed and logged in.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Callable

from zyven.orchestrator.adapters import RunContext, RuntimeAdapter

REPO_NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
FULL_NAME = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")

Runner = Callable[..., subprocess.CompletedProcess]


def plan(task: str) -> tuple[str, str, list[str]]:
    """Validate a task and return (kind, summary, argv). Raises ValueError with a readable reason."""
    try:
        t = json.loads(task)
    except json.JSONDecodeError as e:
        raise ValueError(f"the task must be a JSON object (see the connector docs): {e}") from None
    if not isinstance(t, dict):
        raise ValueError("the task must be a JSON object")
    action = t.get("action")
    if action == "create_repo":
        name = str(t.get("name", ""))
        if not REPO_NAME.fullmatch(name) or name in (".", ".."):
            raise ValueError("create_repo needs a valid repository name")
        private = t.get("private", True)
        if not isinstance(private, bool):
            raise ValueError("private must be true or false")
        argv = ["gh", "repo", "create", name, "--private" if private else "--public"]
        if t.get("description"):
            argv += ["--description", str(t["description"])[:350]]
        return "github.create_repo", f"Create {'private' if private else 'PUBLIC'} GitHub repository {name}", argv
    if action == "create_issue":
        repo, title = str(t.get("repo", "")), str(t.get("title", "")).strip()
        if not FULL_NAME.fullmatch(repo):
            raise ValueError("create_issue needs repo as owner/name")
        if not title:
            raise ValueError("create_issue needs a title")
        argv = ["gh", "issue", "create", "--repo", repo, "--title", title[:256], "--body", str(t.get("body", ""))[:10000]]
        return "github.create_issue", f"Open an issue on {repo}: {title[:80]}", argv
    raise ValueError(f"unknown action {action!r}; use create_repo or create_issue")


class GitHubAdapter(RuntimeAdapter):
    name = "github"
    label = "GitHub"
    open_weight = True  # no model involved: a fixed, validated command
    exposes = {"live_output": True, "tool_calls": False, "approvals": True, "file_changes": False, "tokens": False}
    note = "Creates a repository or an issue with `gh`, after you approve the exact command."

    def __init__(self, runner: Runner | None = None) -> None:
        self._runner = runner or subprocess.run

    def available(self) -> tuple[bool, str]:
        if os.environ.get("ZYVEN_ENABLE_GITHUB") != "1":
            return False, "Off by default (acts on your GitHub account). Set ZYVEN_ENABLE_GITHUB=1 to enable."
        if not shutil.which("gh"):
            return False, "`gh` is not on PATH. Install the GitHub CLI and run `gh auth login`."
        return True, ""

    def run(self, ctx: RunContext) -> int:
        try:
            kind, summary, argv = plan(ctx.run["prompt"])
        except ValueError as e:
            ctx.emit("error", str(e))
            return 2
        shown = " ".join(json.dumps(a) if re.search(r"\s", a) else a for a in argv)
        if not ctx.approve(kind, summary, shown):
            ctx.emit("info", "not approved: nothing was done")
            return 1
        ctx.emit("info", "running: " + shown)
        done = self._runner(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                            stdin=subprocess.DEVNULL)
        for line in (done.stdout + done.stderr).splitlines():
            ctx.emit("out", line)
        return done.returncode
