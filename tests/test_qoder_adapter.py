"""Qoder CLI adapter: tool allowlist, stdin prompt, hub config kept out of argv, sign-in check (stand-in program; no model).

A live run against the real `qodercli` is a manual check (it needs a signed-in account).
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
from zyven.orchestrator.control import Control  # noqa: E402
from zyven.orchestrator.qoder_adapter import DEFAULT_TOOLS, QoderAdapter  # noqa: E402

STAND_IN = textwrap.dedent('''
    import json, os, sys
    prompt = sys.stdin.read()
    cfg = open(".zyven-mcp.json", encoding="utf-8").read() if os.path.exists(".zyven-mcp.json") else None
    open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:], "stdin": prompt, "config": cfg}))
    print('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"a.txt"}}]}}', flush=True)
    print('{"type":"result","is_error":false,"result":"all done","usage":{"input_tokens":3,"output_tokens":4}}', flush=True)
''')


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    script = tmp_path / "fake_qoder.py"
    script.write_text(STAND_IN, encoding="utf-8")
    monkeypatch.setenv("ZYVEN_ENABLE_QODER", "1")
    monkeypatch.delenv("ZYVEN_QODER_MODEL", raising=False)
    return QoderAdapter(executable=[sys.executable, str(script)])


def test_default_command_has_no_shell_or_web_and_the_variadic_tools_option_comes_last(adapter):
    cmd = adapter.command()
    assert cmd[2:6] == ["-p", "-o", "stream-json", "--permission-mode"] and cmd[6] == "accept_edits"
    assert cmd[cmd.index("--tools") + 1:] == list(DEFAULT_TOOLS)
    assert cmd.index("--tools") > cmd.index("--permission-mode")  # nothing is swallowed by the variadic option
    assert "Bash" not in cmd and "bypass_permissions" not in cmd


def test_model_hub_and_full_access_change_only_what_they_should(adapter, monkeypatch):
    monkeypatch.setenv("ZYVEN_QODER_MODEL", "Qwen3.8-Flash")
    cmd = adapter.command(Path("/task"), False, {"url": "http://127.0.0.1:1/mcp", "token": "SECRET"})
    assert cmd[cmd.index("-m") + 1] == "Qwen3.8-Flash"
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--allowed-tools") + 1] == "mcp__zyven"
    assert "SECRET" not in " ".join(cmd) and cmd[-len(DEFAULT_TOOLS):] == list(DEFAULT_TOOLS)
    full = adapter.command(None, True)
    assert "bypass_permissions" in full and "--tools" not in full
    monkeypatch.setenv("ZYVEN_QODER_MODEL", "x; rm -rf /")
    with pytest.raises(ValueError, match="looks wrong"):
        adapter.command()


def test_off_by_default_and_the_program_path_can_be_given(tmp_path, monkeypatch):
    monkeypatch.delenv("ZYVEN_ENABLE_QODER", raising=False)
    ok, why = QoderAdapter().available()
    assert not ok and "ZYVEN_ENABLE_QODER=1" in why
    monkeypatch.setenv("ZYVEN_ENABLE_QODER", "1")
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.delenv("ZYVEN_QODERCLI", raising=False)
    assert QoderAdapter().available()[0] is False
    exe = tmp_path / "qodercli.cmd"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("ZYVEN_QODERCLI", str(exe))
    assert QoderAdapter().available() == (True, "")


def test_sign_in_state_reads_the_status_text(adapter, monkeypatch):
    for out, want in (("Version: 1\nAccount: Not logged in", False), ("Version: 1\nUsername: A\nEmail: a@b.c", True), ("", None)):
        monkeypatch.setattr("zyven.orchestrator.qoder_adapter.run_quiet", lambda cmd, out=out: out)
        assert adapter.sign_in_state()[0] is want


def test_prompt_goes_on_stdin_the_hub_token_stays_in_the_file_and_events_are_parsed(tmp_path, adapter):
    c = Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {"qoder": adapter}, autostart=False)
    nasty = 'make a file & echo hacked | del *.* > nul "quoted" %PATH%'
    rid = c.create(title="", runtime="qoder", prompt=nasty)["id"]
    c._run_worker(rid)
    run = c.get(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    assert seen["stdin"] == nasty and nasty not in " ".join(seen["argv"]) and seen["config"] is None
    texts = [e["text"] for e in run["log"]]
    assert run["status"] == "COMPLETED" and "all done" in texts and any(t.startswith("Write(") for t in texts)
    assert "seen.json" in run["files"]["added"]


def test_the_final_answer_is_shown_once_even_though_qoder_repeats_it(adapter):
    seen: list[tuple[str, str]] = []
    totals: dict = {"in": 0, "out": 0, "cost": 0.0}
    text = '{"type":"assistant","message":{"content":[{"type":"text","text":"G"}]}}'
    result = '{"type":"result","is_error":false,"result":"G","usage":{"input_tokens":0,"output_tokens":0}}'
    for line in (text, result):
        adapter.parse(line, lambda k, t: seen.append((k, t)), totals)
    assert [e for e in seen if e[0] == "out"] == [("out", "G")]
