"""Codex, Antigravity and Claude Code adapters, and the behaviour they share (stand-in programs; no models, no network).

Live checks run only on request: ZYVEN_CODEX_LIVE=1 (needs `codex login`), ZYVEN_AGY_LIVE=1 (needs `agy` signed in).
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator import agy_adapter, claude_adapter, codex_adapter  # noqa: E402
from zyven.orchestrator.adapters import RunContext  # noqa: E402
from zyven.orchestrator.agy_adapter import AgyAdapter  # noqa: E402
from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter  # noqa: E402
from zyven.orchestrator.codex_adapter import CodexAdapter, parse_line  # noqa: E402
from zyven.orchestrator.control import Control  # noqa: E402

# Real lines from `codex exec --json` (codex-cli 0.163), shortened.
MESSAGE = '{"type":"item.completed","item":{"id":"i0","type":"agent_message","text":"Created inside.txt."}}'
CMD_START = '{"type":"item.started","item":{"id":"i1","type":"command_execution","command":"powershell -Command Get-Location","aggregated_output":"","exit_code":null,"status":"in_progress"}}'
CMD_FAIL = '{"type":"item.completed","item":{"id":"i1","type":"command_execution","command":"x","aggregated_output":"Access is denied","exit_code":1,"status":"completed"}}'
CMD_OK = '{"type":"item.completed","item":{"id":"i2","type":"command_execution","command":"x","aggregated_output":"ok","exit_code":0,"status":"completed"}}'
FILE = '{"type":"item.completed","item":{"id":"i3","type":"file_change","changes":[{"path":"C:\\\\w\\\\inside.txt","kind":"add"}],"status":"completed"}}'
DONE = '{"type":"turn.completed","usage":{"input_tokens":46086,"cached_input_tokens":29952,"output_tokens":256,"reasoning_output_tokens":25}}'

STAND_IN = textwrap.dedent('''
    import json, os, sys
    prompt = sys.stdin.read() if os.environ.get("FAKE_STDIN", "1") == "1" else ""
    open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:], "stdin": prompt, "cwd": os.getcwd(),
                                                                "pwd": os.environ.get("PWD")}))
    print("2026-10-24T18:22:44Z ERROR codex_models_manager: failed to refresh available models", file=sys.stderr, flush=True)
    print('{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}', flush=True)
    print('{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":3}}', flush=True)
''')


def _make(cls, tmp_path, monkeypatch, flag):
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setenv(flag, "1")
    return cls(executable=[sys.executable, str(script)])


def _run(tmp_path, adapter, prompt="do it", **kw):
    c = Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {adapter.name: adapter}, autostart=False)
    rid = c.create(title="", runtime=adapter.name, prompt=prompt, **kw)["id"]
    c._run_worker(rid)
    return c, rid, c.get(rid)


# --- Codex ---------------------------------------------------------------------------------------------------

def test_codex_real_events_become_run_events_and_totals():
    events: list[tuple[str, str]] = []
    totals = {"in": 0, "out": 0, "cost": 0.0}
    emit = lambda k, t: events.append((k, t))  # noqa: E731
    for line in (MESSAGE, CMD_START, CMD_OK, CMD_FAIL, FILE, DONE):
        assert parse_line(line, emit, totals) is False
    assert ("out", "Created inside.txt.") in events
    assert events[1] == ("tool", "shell(powershell -Command Get-Location)")
    assert any(k == "tool" and "shell failed (exit 1)" in t and "Access is denied" in t for k, t in events)
    assert ("tool", "edit(add C:\\w\\inside.txt)") in events
    assert totals == {"in": 46086, "out": 256, "cost": 0.0}  # reasoning tokens are inside output_tokens
    assert parse_line('{"type":"turn.failed","error":{"message":"quota"}}', emit, totals) is True
    assert parse_line('{"type":"error","message":"boom"}', emit, totals) is True


def test_codex_runs_in_its_sandbox_with_the_task_folder_and_no_temp_or_network(tmp_path, monkeypatch):
    a = _make(CodexAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_CODEX")
    cmd = a.command(tmp_path / "task")
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    for override in ("sandbox_workspace_write.exclude_tmpdir_env_var=true", "sandbox_workspace_write.exclude_slash_tmp=true",
                     "sandbox_workspace_write.network_access=false"):
        assert override in cmd
    assert cmd[cmd.index("-C") + 1] == str(tmp_path / "task") and cmd[-1] == "-"  # prompt from stdin
    assert "danger" not in " ".join(cmd) and "--dangerously-bypass-approvals-and-sandbox" not in cmd
    monkeypatch.setenv("ZYVEN_CODEX_SANDBOX", "danger-full-access")
    with pytest.raises(ValueError, match="must be one of"):
        a.command(tmp_path)
    monkeypatch.setenv("ZYVEN_CODEX_SANDBOX", "read-only")
    monkeypatch.setenv("ZYVEN_CODEX_MODEL", "x; rm -rf /")
    with pytest.raises(ValueError, match="looks wrong"):
        a.command(tmp_path)


def test_shared_behaviour_prompt_on_stdin_pwd_pinned_stderr_kept_apart(tmp_path, monkeypatch):
    a = _make(CodexAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_CODEX")
    monkeypatch.setenv("PWD", str(ROOT))  # what a parent shell such as Git Bash exports
    nasty = 'write a & b | c > d "e" %PATH% ^f'
    c, rid, run = _run(tmp_path, a, prompt=nasty)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert seen["stdin"] == nasty and nasty not in " ".join(seen["argv"])
    assert Path(seen["cwd"]).resolve() == c.workdir(rid).resolve() and Path(seen["pwd"]).resolve() == c.workdir(rid).resolve()
    log = [(e["kind"], e["text"]) for e in run["log"]]
    assert ("out", "hello") in log and any("7 in / 3 out" in t for k, t in log)
    # the program's own log line is shown as info, and did not disturb the event stream
    assert any(k == "info" and "failed to refresh available models" in t for k, t in log)
    assert not any(k == "out" and "ERROR codex_models_manager" in t for k, t in log)
    assert run["status"] == "COMPLETED"


def test_a_repository_with_its_own_agent_settings_is_refused(tmp_path, monkeypatch):
    for cls, flag, folder in ((CodexAdapter, "ZYVEN_ENABLE_CODEX", ".codex"), (ClaudeCodeAdapter, "ZYVEN_ENABLE_CLAUDE", ".claude"),
                              (AgyAdapter, "ZYVEN_ENABLE_AGY", ".agy")):
        a = _make(cls, tmp_path, monkeypatch, flag)
        cwd = tmp_path / f"repo-{folder.strip('.')}"
        (cwd / folder).mkdir(parents=True)
        events = []
        ctx = RunContext(run={"id": "r", "repo_url": "https://github.com/o/r", "prompt": "x"}, workdir=tmp_path, cwd=cwd,
                         emit=lambda k, t: events.append((k, t)), cancelled=lambda: False)
        assert a.run(ctx) == 2 and events[0][0] == "error" and folder in events[0][1]
        assert not (cwd / "seen.json").exists()  # the program never started


@pytest.mark.skipif(os.name != "nt", reason="the .cmd shim problem exists only on Windows")
def test_a_folder_name_a_cmd_shim_could_misread_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    a = CodexAdapter(executable=["C:\\Tools\\codex.cmd"])
    cwd = tmp_path / "a&b"
    cwd.mkdir()
    events = []
    ctx = RunContext(run={"id": "r", "repo_url": "", "prompt": "x"}, workdir=tmp_path, cwd=cwd,
                     emit=lambda k, t: events.append((k, t)), cancelled=lambda: False)
    assert a.run(ctx) == 2 and "cmd.exe would misread" in events[0][1]


def test_a_program_that_goes_silent_is_stopped_by_the_idle_timeout(tmp_path, monkeypatch):
    import time
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(textwrap.dedent('''
        import sys, time
        sys.stdin.read()
        print('{"type":"turn.started"}', flush=True)
        time.sleep(60)
    '''), encoding="utf-8")
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    a = CodexAdapter(executable=[sys.executable, str(sleeper)])
    a.idle_timeout_s = 2
    started = time.monotonic()
    c, rid, run = _run(tmp_path, a)
    assert time.monotonic() - started < 30  # did not wait out the 60 s sleep
    assert run["status"] == "FAILED" and any("printed nothing for 2s" in e["text"] for e in run["log"])


def test_a_chatty_program_is_not_mistaken_for_a_stuck_one(tmp_path, monkeypatch):
    a = _make(CodexAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_CODEX")
    a.idle_timeout_s = 2
    c, rid, run = _run(tmp_path, a)
    assert run["status"] == "COMPLETED"


# --- availability and sign-in state ----------------------------------------------------------------------------

@pytest.mark.parametrize("cls, flag", [(CodexAdapter, "ZYVEN_ENABLE_CODEX"), (ClaudeCodeAdapter, "ZYVEN_ENABLE_CLAUDE"),
                                       (AgyAdapter, "ZYVEN_ENABLE_AGY")])
def test_off_by_default_and_needs_the_program(cls, flag, monkeypatch):
    monkeypatch.delenv(flag, raising=False)
    ok, why = cls().available()
    assert not ok and f"{flag}=1" in why
    monkeypatch.setenv(flag, "1")
    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, why = cls().available()
    assert not ok and "not on PATH" in why


def test_sign_in_state_is_read_from_each_program(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: name)
    monkeypatch.setattr(codex_adapter, "run_quiet", lambda cmd, timeout=15: "Logged in using ChatGPT\n")
    assert CodexAdapter().sign_in_state()[0] is True
    monkeypatch.setattr(codex_adapter, "run_quiet", lambda cmd, timeout=15: "Not logged in\n")
    assert CodexAdapter().sign_in_state()[0] is False
    monkeypatch.setattr(claude_adapter, "run_quiet", lambda cmd, timeout=15: '{"loggedIn": false, "authMethod": "none"}')
    ok, detail = ClaudeCodeAdapter().sign_in_state()
    assert ok is False and "/login" in detail
    monkeypatch.setattr(claude_adapter, "run_quiet", lambda cmd, timeout=15: '{"loggedIn": true, "authMethod": "claude.ai"}')
    assert ClaudeCodeAdapter().sign_in_state()[0] is True
    monkeypatch.setattr(agy_adapter, "run_quiet", lambda cmd, timeout=25: "Error: Please sign in to view available models.")
    ok, detail = AgyAdapter().sign_in_state()
    assert ok is False and "agy" in detail
    monkeypatch.setattr(agy_adapter, "run_quiet", lambda cmd, timeout=25: "")
    assert AgyAdapter().sign_in_state()[0] is None  # cannot tell: say so, do not guess


def test_status_is_reported_in_the_runtime_list_and_cached(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    a = CodexAdapter()
    s = a.status(wait=True)
    assert s["installed"] is False and "not installed" in s["detail"]
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: "codex")
    monkeypatch.setattr(codex_adapter, "run_quiet", lambda cmd, timeout=15: calls.append(cmd) or "Logged in\n")
    b = CodexAdapter()
    b.status(wait=True), b.status(wait=True), b.status(wait=True)
    assert len(calls) == 1  # asking the program is slow: cached for a minute


def test_a_page_load_never_waits_for_the_slow_sign_in_check(monkeypatch):
    import threading
    import time
    release = threading.Event()
    monkeypatch.setattr("shutil.which", lambda name: "codex")

    def slow(cmd, timeout=15):
        release.wait(10)  # a program that takes a long time to answer
        return "Logged in using ChatGPT"

    monkeypatch.setattr(codex_adapter, "run_quiet", slow)
    a = CodexAdapter()
    started = time.monotonic()
    first = a.info()["status"]
    assert time.monotonic() - started < 1 and first["detail"] == "Checking sign-in…" and first["signed_in"] is None
    release.set()
    for _ in range(100):  # the background check finishes and the next page poll sees the real answer
        if a.info()["status"]["signed_in"] is True:
            break
        time.sleep(0.05)
    assert a.info()["status"]["signed_in"] is True


# --- Claude Code -----------------------------------------------------------------------------------------------

def test_claude_takes_its_prompt_on_stdin_and_never_gets_a_shell_or_repo_settings(tmp_path, monkeypatch):
    a = _make(ClaudeCodeAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_CLAUDE")
    cmd = a.command()
    assert cmd[cmd.index("--tools") + 1] == claude_adapter.DEFAULT_TOOLS and "Bash" not in claude_adapter.DEFAULT_TOOLS
    assert cmd[cmd.index("--setting-sources") + 1] == "user"  # a checked-out repo cannot bring hooks
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd
    c, rid, run = _run(tmp_path, a, prompt="make a file & echo hacked")
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert seen["stdin"] == "make a file & echo hacked" and "hacked" not in " ".join(seen["argv"])


# --- Antigravity (not verified live) -------------------------------------------------------------------------------

def test_agy_passes_the_prompt_as_the_last_argument_and_never_skips_permissions(tmp_path, monkeypatch):
    a = _make(AgyAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_AGY")
    cmd = a.command()
    assert cmd[-1] == "--print" and "--sandbox" in cmd and cmd[cmd.index("--mode") + 1] == "accept-edits"
    assert "--dangerously-skip-permissions" not in cmd
    monkeypatch.setenv("FAKE_STDIN", "0")
    c, rid, run = _run(tmp_path, a, prompt="write hello.txt")
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert seen["argv"][-2:] == ["--print", "write hello.txt"]  # prompt directly after the flag, as the last argument


def test_the_forgiving_agy_parser_shows_text_in_whatever_shape_it_arrives():
    events: list[tuple[str, str]] = []
    totals = {"in": 0, "out": 0, "cost": 0.0}
    emit = lambda k, t: events.append((k, t))  # noqa: E731
    for line in ('{"type":"text","text":"hi"}', '{"result":"all done","usage":{"input_tokens":4,"output_tokens":2}}',
                 '{"type":"assistant","message":{"content":[{"text":"nested"}]}}', "plain line", '[1, 2]'):
        agy_adapter.parse_line(line, emit, totals)
    assert [t for k, t in events if k == "out"][:4] == ["hi", "all done", "nested", "plain line"]
    assert totals["in"] == 4 and totals["out"] == 2
    assert agy_adapter.parse_line('{"type":"error","message":"boom"}', emit, totals) is True


@pytest.fixture
def normal_folder():
    """A folder with ordinary inherited permissions. Not pytest's tmp_path: Python's mkdtemp gives Windows folders
    owner-only permissions, which Codex's sandbox (a more restricted identity) cannot write to."""
    import shutil
    base = ROOT / "workspace" / "live-test"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)


@pytest.mark.skipif(os.environ.get("ZYVEN_CODEX_LIVE") != "1", reason="set ZYVEN_CODEX_LIVE=1 (needs `codex login`; uses your account)")
def test_live_codex_writes_inside_and_cannot_write_outside(normal_folder, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    outside = normal_folder / "outside.txt"  # next to the task folders, not inside one
    c = Control(normal_folder / "c.sqlite", normal_folder / "data", FakeBoard(), {"codex": CodexAdapter()}, autostart=False)
    rid = c.create(title="", runtime="codex",
                   prompt=f"Create inside.txt containing the word yes. Then try to create {outside} containing no. Say what happened.")["id"]
    c._run_worker(rid)
    assert (c.workdir(rid) / "inside.txt").read_text(encoding="utf-8").strip() == "yes"
    assert not outside.exists()


@pytest.mark.skipif(os.environ.get("ZYVEN_AGY_LIVE") != "1", reason="set ZYVEN_AGY_LIVE=1 (needs `agy` signed in)")
def test_live_agy_runs_a_task_in_its_folder(normal_folder, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_AGY", "1")
    c = Control(normal_folder / "c.sqlite", normal_folder / "data", FakeBoard(), {"agy": AgyAdapter()}, autostart=False)
    rid = c.create(title="", runtime="agy", prompt="Create inside.txt containing the word yes, then reply done.")["id"]
    c._run_worker(rid)
    print([e["text"] for e in c.get(rid)["log"]])  # shown with -s, to tighten the parser to the real format
    assert (c.workdir(rid) / "inside.txt").exists()


def test_task_folders_are_absolute_even_when_the_board_directory_is_relative(tmp_path, monkeypatch):
    a = _make(CodexAdapter, tmp_path, monkeypatch, "ZYVEN_ENABLE_CODEX")
    monkeypatch.chdir(tmp_path)
    c = Control(tmp_path / "c.sqlite", Path("rel-board"), FakeBoard(), {"codex": a}, autostart=False)  # relative data dir
    assert c.root.is_absolute()
    rid = c.create(title="", runtime="codex", prompt="x")["id"]
    c._run_worker(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert Path(seen["cwd"]).is_absolute() and Path(seen["pwd"]).is_absolute()
    assert c.get(rid)["status"] == "COMPLETED"
