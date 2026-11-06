"""Offline tests for coding agents as compile-role providers. A stand-in program plays the agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from zyven.ai.agent_provider import AgentProvider, extract_json, flatten, provider_for
from zyven.ai.provider import ProviderError

FAKE_CODEX = r'''
import json, os, sys
prompt = sys.stdin.read()
open(os.path.join(os.getcwd(), "seen.txt"), "w").close()  # proves it ran in its own folder
reply = os.environ.get("FAKE_REPLY", 'Sure, here it is:\n```json\n{"name": "iban", "count": 2}\n```')
if "FAIL" in prompt:
    print(json.dumps({"type": "turn.failed", "error": {"message": "quota exhausted"}}))
    sys.exit(1)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "thinking..."}}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": reply}}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 30}}))
'''


class Small(BaseModel):
    name: str
    count: int


@pytest.fixture
def fake_codex(tmp_path) -> list[str]:
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE_CODEX, encoding="utf-8")
    return [sys.executable, str(script)]


def test_structured_answer_comes_from_the_last_agent_message(fake_codex):
    p = AgentProvider("codex", executable=fake_codex)
    out = p.generate_structured([{"role": "system", "content": "be exact"}, {"role": "user", "content": "go"}], Small)
    assert out == Small(name="iban", count=2)
    assert p.stats.calls == 1 and p.stats.prompt_tokens == 120 and p.stats.completion_tokens == 30
    assert p.label.endswith("[coding agent]")


def test_codex_runs_read_only_in_an_empty_temporary_folder(fake_codex):
    p = AgentProvider("codex", executable=fake_codex)
    cmd = p.command(Path("."))
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert "--ephemeral" in cmd and "--ignore-user-config" in cmd


def test_claude_gets_no_tools():
    p = AgentProvider("claude", executable=["claude-stand-in"])
    cmd = p.command(Path("."))
    assert cmd[cmd.index("--tools") + 1] == ""


def test_a_failed_agent_run_is_a_provider_error(fake_codex):
    p = AgentProvider("codex", executable=fake_codex, max_retries=1)
    with pytest.raises(ProviderError, match="quota exhausted"):
        p.chat([{"role": "user", "content": "FAIL please"}])
    assert p.stats.failures == 1


def test_agents_cannot_drive_the_tool_loop(fake_codex):
    p = AgentProvider("codex", executable=fake_codex)
    with pytest.raises(ProviderError, match="tool loop"):
        p.chat([{"role": "user", "content": "x"}], tools=[{"type": "function", "function": {"name": "f"}}])


def test_model_name_is_checked_and_passed_on(fake_codex):
    with pytest.raises(ProviderError):
        AgentProvider("codex", model="gpt; rm -rf /", executable=fake_codex)
    p = AgentProvider("codex", model="gpt-5.5", executable=fake_codex)
    cmd = p.command(Path("."))
    assert cmd[cmd.index("-m") + 1] == "gpt-5.5"


def test_extract_json_handles_prose_and_fences():
    assert json.loads(extract_json('Here you go: {"a": 1} hope it helps')) == {"a": 1}
    assert json.loads(extract_json('```json\n{"a": [1, 2]}\n```')) == {"a": [1, 2]}
    assert extract_json("no json at all") == "no json at all"


def test_flatten_includes_roles_and_the_schema():
    fmt = {"type": "json_schema", "json_schema": {"name": "Small", "schema": Small.model_json_schema()}}
    text = flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], fmt)
    assert "### SYSTEM\nS" in text and "### USER\nU" in text and '"count"' in text


def test_provider_for_parses_choices():
    p = provider_for("claude:opus")
    assert isinstance(p, AgentProvider) and p.agent == "claude" and p.model == "opus"
    with pytest.raises(ProviderError, match="unknown provider"):
        provider_for("chatgpt")
