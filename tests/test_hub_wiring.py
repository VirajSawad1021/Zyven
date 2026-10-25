"""How the Control center hands the hub to an agent: one token per run, revoked after, never on a command line."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_control import FakeBoard  # noqa: E402
from zyven.orchestrator.adapters import DockerAdapter, RunContext, RuntimeAdapter  # noqa: E402
from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter  # noqa: E402
from zyven.orchestrator.codex_adapter import CodexAdapter  # noqa: E402
from zyven.orchestrator.control import Control, runtime_info  # noqa: E402
from zyven.orchestrator.opencode_adapter import OpenCodeAdapter  # noqa: E402

HUB = {"url": "http://127.0.0.1:8765/hub/mcp", "token": "run-token-abc"}


class FakeHub:
    def __init__(self) -> None:
        self.issued: list[str] = []
        self.revoked: list[str] = []

    def issue(self, run_id: str) -> str:
        self.issued.append(run_id)
        return "run-token-abc"

    def revoke_from_thread(self, run_id: str) -> None:
        self.revoked.append(run_id)


class Recorder(RuntimeAdapter):
    name, label, supports_hub = "rec", "Recorder", True

    def __init__(self, boom: bool = False) -> None:
        self.seen: RunContext | None = None
        self.boom = boom

    def run(self, ctx: RunContext) -> int:
        self.seen = ctx
        if self.boom:
            raise RuntimeError("the agent crashed")
        return 0


def _control(tmp_path, *adapters) -> tuple[Control, FakeHub]:
    c = Control(tmp_path / "c.sqlite", tmp_path, FakeBoard(), {a.name: a for a in adapters}, autostart=False)
    c.hub, c.hub_url = FakeHub(), lambda: HUB["url"]
    return c, c.hub


def test_a_run_gets_a_token_only_when_it_asked_for_zyven_tools(tmp_path):
    rec = Recorder()
    c, hub = _control(tmp_path, rec)
    plain = c.create(title="", runtime="rec", prompt="x")["id"]
    c._run_worker(plain)
    assert rec.seen.hub is None and hub.issued == []
    asked = c.create(title="", runtime="rec", prompt="x", zyven_tools=True)
    assert asked["zyven_tools"] is True
    c._run_worker(asked["id"])
    assert rec.seen.hub == HUB and hub.issued == [asked["id"]]


def test_the_token_is_revoked_even_when_the_agent_crashes(tmp_path):
    c, hub = _control(tmp_path, Recorder(boom=True))
    rid = c.create(title="", runtime="rec", prompt="x", zyven_tools=True)["id"]
    c._run_worker(rid)
    assert c.get(rid)["status"] == "FAILED" and hub.revoked == [rid]


def test_runtimes_that_cannot_use_the_hub_are_refused_and_the_list_says_who_can(tmp_path, monkeypatch):
    c, _ = _control(tmp_path, Recorder(), DockerAdapter())
    with pytest.raises(ValueError, match="cannot use Zyven's tools"):
        c.create(title="", runtime="docker", prompt="echo hi", zyven_tools=True)
    with pytest.raises(ValueError, match="cannot use Zyven's tools"):
        c.create(title="", runtime="zyven", prompt="x", zyven_tools=True)
    info = runtime_info({"rec": Recorder(), "docker": DockerAdapter()})
    assert info["rec"]["supports_hub"] is True and info["docker"]["supports_hub"] is False


def test_codex_is_pointed_at_the_hub_in_approve_mode_with_the_token_in_the_environment_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    script = tmp_path / "fake_codex.py"
    script.write_text(textwrap.dedent('''
        import json, os, sys
        sys.stdin.read()
        open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:], "token": os.environ.get("ZYVEN_HUB_TOKEN")}))
        print('{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}', flush=True)
    '''), encoding="utf-8")
    a = CodexAdapter(executable=[sys.executable, str(script)])
    c, _ = _control(tmp_path, a)
    rid = c.create(title="", runtime="codex", prompt="x", zyven_tools=True)["id"]
    c._run_worker(rid)
    seen = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))
    argv = seen["argv"]
    assert f"mcp_servers.zyven.url={HUB['url']}" in argv
    assert "mcp_servers.zyven.bearer_token_env_var=ZYVEN_HUB_TOKEN" in argv
    assert "mcp_servers.zyven.default_tools_approval_mode=approve" in argv  # the approval card is the one asked
    assert "mcp_servers.zyven.tool_timeout_sec=3600" in argv
    assert seen["token"] == HUB["token"] and HUB["token"] not in " ".join(argv)
    # a task that did not ask for the hub sees none of it
    rid2 = c.create(title="", runtime="codex", prompt="x")["id"]
    c._run_worker(rid2)
    seen2 = json.loads((c.workdir(rid2) / "seen.json").read_text(encoding="utf-8"))
    assert not any("mcp_servers" in x for x in seen2["argv"]) and seen2["token"] is None


def test_opencode_gets_the_hub_in_its_project_config_and_that_file_is_not_a_result(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_OPENCODE", "1")
    a = OpenCodeAdapter(executable=[sys.executable, "-c", "pass"])
    c, _ = _control(tmp_path, a)
    rid = c.create(title="", runtime="opencode", prompt="x", zyven_tools=True)["id"]
    c._run_worker(rid)
    cfg = json.loads((c.workdir(rid) / "opencode.json").read_text(encoding="utf-8"))
    mcp = cfg["mcp"]["zyven"]
    assert mcp["type"] == "remote" and mcp["url"] == HUB["url"] and mcp["headers"]["Authorization"] == "Bearer run-token-abc"
    assert cfg["permission"]["bash"] == "deny"  # the hub does not loosen the sandbox
    assert "opencode.json" not in c.get(rid)["files"]["added"]
    rid2 = c.create(title="", runtime="opencode", prompt="x")["id"]
    c._run_worker(rid2)
    assert "mcp" not in json.loads((c.workdir(rid2) / "opencode.json").read_text(encoding="utf-8"))


def test_claude_reads_the_hub_from_a_file_so_the_token_is_not_in_its_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_CLAUDE", "1")
    script = tmp_path / "fake_claude.py"
    script.write_text(textwrap.dedent('''
        import json, sys
        sys.stdin.read()
        open("seen.json", "w", encoding="utf-8").write(json.dumps({"argv": sys.argv[1:]}))
        print('{"type":"result","result":"ok","usage":{"input_tokens":1,"output_tokens":1}}', flush=True)
    '''), encoding="utf-8")
    c, _ = _control(tmp_path, ClaudeCodeAdapter(executable=[sys.executable, str(script)]))
    rid = c.create(title="", runtime="claude", prompt="x", zyven_tools=True)["id"]
    c._run_worker(rid)
    argv = json.loads((c.workdir(rid) / "seen.json").read_text(encoding="utf-8"))["argv"]
    assert argv[argv.index("--mcp-config") + 1].endswith(".zyven-mcp.json") and "--strict-mcp-config" in argv
    assert HUB["token"] not in " ".join(argv)
    cfg = json.loads((c.workdir(rid) / ".zyven-mcp.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"]["zyven"]["headers"]["Authorization"] == "Bearer run-token-abc"
    assert ".zyven-mcp.json" not in c.get(rid)["files"]["added"]


def test_waiting_for_an_approval_is_not_mistaken_for_a_stuck_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ENABLE_CODEX", "1")
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(textwrap.dedent('''
        import sys, time
        sys.stdin.read()
        print('{"type":"turn.started"}', flush=True)
        time.sleep(5)
        print('{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}', flush=True)
    '''), encoding="utf-8")
    a = CodexAdapter(executable=[sys.executable, str(sleeper)])
    a.idle_timeout_s = 2
    c, _ = _control(tmp_path, a)
    rid = c.create(title="", runtime="codex", prompt="x")["id"]
    c.approvals_for = lambda *args, **kw: [{"id": "pending"}]  # the run has an approval card waiting for the user
    c._run_worker(rid)
    run = c.get(rid)
    assert run["status"] == "COMPLETED" and not any("printed nothing" in e["text"] for e in run["log"])
