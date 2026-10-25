"""OpenCode adapter: permission lockdown, stdin prompt, event parsing, cancel (stand-in program; no model, no network).

A live check against the real `opencode` runs only with ZYVEN_OPENCODE_LIVE=1.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator.control import Control  # noqa: E402
from zyven.orchestrator.opencode_adapter import OpenCodeAdapter, parse_line, permission_config  # noqa: E402

# Lines captured from `opencode run --format json` (v2.1.4), shortened.
WRITE = ('{"type":"tool_use","part":{"type":"tool","tool":"write","state":{"status":"completed",'
         '"input":{"path":"hello.txt","content":"hi"},"output":"Created file successfully: hello.txt"}}}')
DENIED = '{"type":"tool_use","part":{"type":"tool","tool":"write","state":{"status":"error","input":{"path":"C:/x.txt"},"output":""}}}'
FINISH = '{"type":"step_finish","part":{"type":"step-finish","cost":0.002,"tokens":{"input":3494,"output":73,"reasoning":27}}}'
TEXT = '{"type":"text","part":{"type":"text","text":"done"}}'

STAND_IN = textwrap.dedent('''
    import json, os, sys, time
    prompt = sys.stdin.read()
    cfg = open("opencode.json", encoding="utf-8").read() if os.path.exists("opencode.json") else None
    open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:], "stdin": prompt, "config": cfg,
                                                                "cwd": os.getcwd(), "pwd": os.environ.get("PWD")}))
    mode = os.environ.get("FAKE_MODE", "ok")
    print('{"type":"tool_use","part":{"type":"tool","tool":"write","state":{"status":"completed","input":{"path":"a.txt"}}}}', flush=True)
    if mode == "sleep":
        time.sleep(60)
    if mode == "error":
        print('{"type":"error","error":{"message":"model unavailable"}}', flush=True)
    print('{"type":"text","part":{"type":"text","text":"finished"}}', flush=True)
    print('{"type":"step_finish","part":{"cost":0,"tokens":{"input":10,"output":5,"reasoning":0}}}', flush=True)
''')


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    script = tmp_path / "fake_opencode.py"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setenv("ZYVEN_ENABLE_OPENCODE", "1")
    monkeypatch.delenv("ZYVEN_OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("ZYVEN_OPENCODE_ALLOW_SHELL", raising=False)
    return OpenCodeAdapter(executable=[sys.executable, str(script)])


def _control(tmp_path, adapter) -> Control:
    return Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {"opencode": adapter}, autostart=False)


def test_default_permissions_deny_shell_web_and_anything_outside_the_folder():
    perm = permission_config()["permission"]
    assert perm["bash"] == "deny" and perm["external_directory"] == "deny"
    assert perm["webfetch"] == "deny" and perm["websearch"] == "deny" and perm["edit"] == "allow"
    only_bash = {k for k in perm if perm[k] != permission_config(True)["permission"][k]}
    assert only_bash == {"bash"}  # allowing the shell changes nothing else


def test_real_event_lines_become_run_events_and_token_totals():
    events: list[tuple[str, str]] = []
    totals = {"in": 0, "out": 0, "cost": 0.0}
    emit = lambda k, t: events.append((k, t))  # noqa: E731
    for line in (WRITE, DENIED, TEXT, FINISH):
        assert parse_line(line, emit, totals) is False
    assert events[0] == ("tool", 'write({"path": "hello.txt", "content": "hi"})')
    assert events[1][0] == "tool" and "blocked or failed" in events[1][1]
    assert ("out", "done") in events
    assert totals == {"in": 3494, "out": 100, "cost": 0.002}  # output counts reasoning tokens too
    assert parse_line('{"type":"error","error":{"message":"boom"}}', emit, totals) is True
    parse_line("plain text", emit, totals)
    assert events[-1] == ("out", "plain text")


def test_off_by_default_and_needs_the_program(monkeypatch):
    monkeypatch.delenv("ZYVEN_ENABLE_OPENCODE", raising=False)
    ok, why = OpenCodeAdapter().available()
    assert not ok and "ZYVEN_ENABLE_OPENCODE=1" in why
    monkeypatch.setenv("ZYVEN_ENABLE_OPENCODE", "1")
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, why = OpenCodeAdapter().available()
    assert not ok and "not on PATH" in why


def test_the_model_setting_is_validated(adapter, monkeypatch):
    monkeypatch.setenv("ZYVEN_OPENCODE_MODEL", "opencode/deepseek-v4.1-flash-free")
    assert adapter.command()[-2:] == ["-m", "opencode/deepseek-v4.1-flash-free"]
    monkeypatch.setenv("ZYVEN_OPENCODE_MODEL", "x; rm -rf /")
    with pytest.raises(ValueError, match="looks wrong"):
        adapter.command()


def test_prompt_goes_on_stdin_never_in_the_arguments_and_the_folder_is_locked(tmp_path, adapter):
    c = _control(tmp_path, adapter)
    nasty = 'make a file & echo hacked | del *.* > nul "quoted" %PATH% ^caret'
    rid = c.create(title="", runtime="opencode", prompt=nasty)["id"]
    c._run_worker(rid)
    run = c.get(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert seen["stdin"] == nasty and nasty not in " ".join(seen["argv"])
    assert seen["argv"][:3] == ["run", "--standalone", "--format"]
    assert json.loads(seen["config"])["permission"]["bash"] == "deny"  # in place before the program started
    assert run["status"] == "COMPLETED" and "opencode.json" not in run["files"]["added"]  # Zyven's own file is not a result
    assert (c.workdir(rid) / "opencode.json").exists()  # but it was written, before the program started
    texts = [e["text"] for e in run["log"]]
    assert "finished" in texts and any("10 in / 5 out" in t for t in texts) and any(t.startswith("write(") for t in texts)


def test_the_program_sees_the_task_folder_even_if_the_parent_shell_has_another_pwd(tmp_path, adapter, monkeypatch):
    monkeypatch.setenv("PWD", str(ROOT))  # what a parent shell such as Git Bash exports
    monkeypatch.setenv("OLDPWD", str(ROOT))
    c = _control(tmp_path, adapter)
    rid = c.create(title="", runtime="opencode", prompt="x")["id"]
    c._run_worker(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert Path(seen["cwd"]).resolve() == c.workdir(rid).resolve() and Path(seen["pwd"]).resolve() == c.workdir(rid).resolve()


def test_shell_is_allowed_only_when_explicitly_switched_on(tmp_path, adapter, monkeypatch):
    monkeypatch.setenv("ZYVEN_OPENCODE_ALLOW_SHELL", "1")
    c = _control(tmp_path, adapter)
    rid = c.create(title="", runtime="opencode", prompt="x")["id"]
    c._run_worker(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert json.loads(seen["config"])["permission"]["bash"] == "allow"
    assert any("shell ALLOWED" in e["text"] for e in c.get(rid)["log"])


def test_an_error_event_fails_the_run(tmp_path, adapter, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "error")
    c = _control(tmp_path, adapter)
    rid = c.create(title="", runtime="opencode", prompt="x")["id"]
    c._run_worker(rid)
    assert c.get(rid)["status"] == "FAILED"


def test_a_repository_with_its_own_opencode_settings_is_refused(tmp_path, adapter):
    from zyven.orchestrator.adapters import RunContext

    cwd = tmp_path / "repo"
    (cwd / ".opencode").mkdir(parents=True)
    events = []
    ctx = RunContext(run={"id": "r1", "repo_url": "https://github.com/o/r", "prompt": "x"}, workdir=tmp_path, cwd=cwd,
                     emit=lambda k, t: events.append((k, t)), cancelled=lambda: False)
    assert adapter.run(ctx) == 2 and events[0][0] == "error" and ".opencode" in events[0][1]
    assert not (cwd / "opencode.json").exists()  # nothing was started or written


def test_cancel_stops_a_running_program(tmp_path, adapter, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    c = _control(tmp_path, adapter)
    rid = c.create(title="", runtime="opencode", prompt="x")["id"]
    t = threading.Thread(target=c._run_worker, args=(rid,))
    started = time.monotonic()
    t.start()
    for _ in range(100):  # wait until the program is running
        if (c.workdir(rid) / "seen.json").exists():
            break
        time.sleep(0.05)
    c.cancel(rid)
    t.join(15)
    assert not t.is_alive() and time.monotonic() - started < 30  # did not wait out the 60 s sleep
    assert c.get(rid)["status"] == "CANCELLED"


@pytest.mark.skipif(os.environ.get("ZYVEN_OPENCODE_LIVE") != "1", reason="set ZYVEN_OPENCODE_LIVE=1 (uses a free hosted model)")
def test_live_opencode_writes_a_file_and_cannot_leave_its_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_OPENCODE", "1")
    monkeypatch.setenv("ZYVEN_OPENCODE_MODEL", os.environ.get("ZYVEN_OPENCODE_MODEL", "opencode/deepseek-v4.1-flash-free"))
    outside = tmp_path / "outside.txt"
    c = Control(tmp_path / "c.sqlite", tmp_path / "data", FakeBoard(), {"opencode": OpenCodeAdapter()}, autostart=False)
    rid = c.create(title="", runtime="opencode",
                   prompt=f"Create inside.txt containing the word yes. Then also try to create {outside} containing no. Reply done.")["id"]
    c._run_worker(rid)
    assert (c.workdir(rid) / "inside.txt").read_text(encoding="utf-8").strip() == "yes"
    assert not outside.exists()
