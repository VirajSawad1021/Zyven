"""Full PC access: an opt-in, per-task mode that removes the sandbox for the agents that support it.

It needs two deliberate steps (ZYVEN_ALLOW_FULL_ACCESS=1, then the choice on the task), is refused for runtimes that
cannot do it, and cannot be combined with a repeating schedule.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator.adapters import DockerAdapter  # noqa: E402
from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter  # noqa: E402
from zyven.orchestrator.codex_adapter import CodexAdapter  # noqa: E402
from zyven.orchestrator.control import Control, runtime_info  # noqa: E402
from zyven.orchestrator.opencode_adapter import OpenCodeAdapter, permission_config  # noqa: E402

STAND_IN = textwrap.dedent('''
    import json, os, sys
    sys.stdin.read()
    open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:]}))
    print('{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}', flush=True)
''')


@pytest.fixture
def codex(tmp_path, monkeypatch):
    script = tmp_path / "fake_codex.py"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    return CodexAdapter(executable=[sys.executable, str(script)])


def _control(tmp_path, *adapters) -> Control:
    return Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {a.name: a for a in adapters}, autostart=False)


def test_it_is_refused_unless_the_machine_owner_allowed_it(tmp_path, codex, monkeypatch):
    monkeypatch.delenv("ZYVEN_ALLOW_FULL_ACCESS", raising=False)
    c = _control(tmp_path, codex)
    with pytest.raises(ValueError, match="ZYVEN_ALLOW_FULL_ACCESS=1"):
        c.create(title="", runtime="codex", prompt="x", full_access=True)
    assert c.create(title="", runtime="codex", prompt="x")["full_access"] is False  # the default stays sandboxed


def test_it_is_refused_for_runtimes_that_cannot_do_it_and_for_repeating_tasks(tmp_path, codex, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_FULL_ACCESS", "1")
    c = _control(tmp_path, codex, DockerAdapter())
    with pytest.raises(ValueError, match="cannot run with full PC access"):
        c.create(title="", runtime="docker", prompt="echo hi", full_access=True)
    with pytest.raises(ValueError, match="cannot run with full PC access"):
        c.create(title="", runtime="zyven", prompt="x", full_access=True)
    with pytest.raises(ValueError, match="repeating task"):
        c.create(title="", runtime="codex", prompt="x", full_access=True, repeat_secs=3600)


def test_an_allowed_task_is_remembered_shown_and_started_without_the_sandbox(tmp_path, codex, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_FULL_ACCESS", "1")
    c = _control(tmp_path, codex)
    run = c.create(title="", runtime="codex", prompt="x", full_access=True)
    assert run["full_access"] is True and [r for r in c.list() if r["id"] == run["id"]][0]["full_access"] is True
    c._run_worker(run["id"])
    seen = json.loads((c.workdir(run["id"]) / "seen.json").read_text(encoding="utf-8"))
    argv = seen["argv"]
    assert argv[argv.index("-s") + 1] == "danger-full-access"
    assert not any("sandbox_workspace_write" in a for a in argv)  # those limits belong to the sandboxed mode
    log = [(e["kind"], e["text"]) for e in c.get(run["id"])["log"]]
    assert any(k == "error" and "FULL PC ACCESS" in t and "NOT sandboxed" in t for k, t in log)
    assert any("NO SANDBOX" in t for k, t in log)


def test_a_normal_task_on_the_same_runtime_stays_sandboxed(tmp_path, codex, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_FULL_ACCESS", "1")  # allowed, but not asked for on this task
    c = _control(tmp_path, codex)
    rid = c.create(title="", runtime="codex", prompt="x")["id"]
    c._run_worker(rid)
    argv = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))["argv"]
    assert argv[argv.index("-s") + 1] == "workspace-write" and "sandbox_workspace_write.network_access=false" in argv
    assert not any("FULL PC ACCESS" in e["text"] for e in c.get(rid)["log"])


def test_even_with_full_access_codex_does_not_load_the_users_plugins(tmp_path, codex):
    cmd = codex.command(tmp_path, full=True)
    assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd
    assert {"computer_use", "browser_use", "apps"} <= {cmd[i + 1] for i, x in enumerate(cmd) if x == "--disable"}


def test_the_environment_cannot_switch_codex_to_full_access_behind_a_tasks_back(codex, monkeypatch):
    monkeypatch.setenv("ZYVEN_CODEX_SANDBOX", "danger-full-access")
    with pytest.raises(ValueError, match="never through ZYVEN_CODEX_SANDBOX"):
        codex.command(None)


def test_opencode_full_access_lifts_shell_folder_and_web_limits_and_nothing_else():
    normal, full = permission_config()["permission"], permission_config(full=True)["permission"]
    assert (normal["bash"], normal["external_directory"], normal["webfetch"], normal["websearch"]) == ("deny",) * 4
    assert (full["bash"], full["external_directory"], full["webfetch"], full["websearch"]) == ("allow",) * 4
    assert {k for k in normal if normal[k] != full[k]} == {"bash", "external_directory", "webfetch", "websearch"}


def test_opencode_writes_the_open_permissions_only_for_a_full_access_task(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_OPENCODE", "1")
    a = OpenCodeAdapter(executable=[sys.executable, "-c", "pass"])
    from zyven.orchestrator.adapters import RunContext

    for full in (False, True):
        folder = tmp_path / f"f{full}"
        folder.mkdir()
        ctx = RunContext(run={"id": "r", "repo_url": "", "prompt": "x", "full_access": full}, workdir=folder, cwd=folder,
                         emit=lambda k, t: None, cancelled=lambda: False)
        note = a.prepare(ctx)
        cfg = json.loads((folder / "opencode.json").read_text(encoding="utf-8"))["permission"]
        assert (cfg["bash"] == "allow") is full and ("NO RESTRICTIONS" in note) is full


def test_claude_full_access_adds_the_shell_and_stops_asking(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude")
    a = ClaudeCodeAdapter()
    normal, full = a.command(), a.command(full=True)
    assert "Bash" not in normal[normal.index("--tools") + 1] and normal[normal.index("--permission-mode") + 1] == "acceptEdits"
    assert "Bash" in full[full.index("--tools") + 1] and full[full.index("--permission-mode") + 1] == "bypassPermissions"
    assert full[full.index("--setting-sources") + 1] == "user"  # a repository's own settings are still ignored


def test_the_runtime_list_says_which_runtimes_support_it_and_whether_it_is_allowed(codex, monkeypatch):
    monkeypatch.delenv("ZYVEN_ALLOW_FULL_ACCESS", raising=False)
    info = runtime_info({"codex": codex, "docker": DockerAdapter()})
    assert info["codex"]["full_access"] == {"supported": True, "allowed": False} and "full_access" not in info["docker"]
    monkeypatch.setenv("ZYVEN_ALLOW_FULL_ACCESS", "1")
    assert runtime_info({"codex": codex})["codex"]["full_access"]["allowed"] is True
