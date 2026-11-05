"""Coding agents (Codex, Claude Code, Antigravity, OpenCode, Qoder) as model providers for the compile roles.

Every compile role asks one question and wants one JSON answer back (`generate_structured`). A coding agent run
headless can answer that question just like a chat API, so this provider turns "one chat call" into "one headless
agent run":

  * the agent runs in a fresh, empty temporary folder that is deleted afterwards;
  * its tools are cut to the minimum the program allows (Codex read-only sandbox, Claude Code with no tools,
    OpenCode with every permission denied); it is asked to answer in text, not to touch files;
  * the conversation is flattened into one prompt, which goes on stdin (or as an argument to a native program);
  * the last message the agent prints is the reply; for structured calls the JSON object is cut out of it.

The agent's answer is trusted exactly as much as a chat model's: not at all. It goes through the same schema
validation, reference resolution, policy check and six sandbox gates. Which agent and model wrote each role's
output is recorded in provenance.json.

Agent runs cannot drive Zyven's own tool loop (`chat(tools=...)`): an agent has its own tools. Use a chat model for
the self-extending agent and pick agents per compile role.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from zyven.ai.provider import ChatResult, ModelProvider, ProviderError, ProviderStats

AGENT_NAMES = ("codex", "claude", "agy", "opencode", "qoder")
DEFAULT_TIMEOUT_S = 900.0
_MODEL_RE = re.compile(r"[\w./:#\-\[\]]{1,100}")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _adapter(name: str):
    """The Control center adapter for `name`; its command line and output parser are reused as they are."""
    if name == "codex":
        from zyven.orchestrator.codex_adapter import CodexAdapter
        return CodexAdapter()
    if name == "claude":
        from zyven.orchestrator.claude_adapter import ClaudeCodeAdapter
        return ClaudeCodeAdapter()
    if name == "agy":
        from zyven.orchestrator.agy_adapter import AgyAdapter
        return AgyAdapter()
    if name == "opencode":
        from zyven.orchestrator.opencode_adapter import OpenCodeAdapter
        return OpenCodeAdapter()
    if name == "qoder":
        from zyven.orchestrator.qoder_adapter import QoderAdapter
        return QoderAdapter()
    raise ProviderError(f"unknown coding agent {name!r}; choose one of {', '.join(AGENT_NAMES)}")


def extract_json(text: str) -> str:
    """The JSON object inside an agent's reply (agents sometimes add a sentence or a code fence around it)."""
    t = _FENCE_RE.sub("", text.strip()).strip()
    try:
        json.loads(t)
        return t
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if 0 <= start < end:
        inner = t[start:end + 1]
        try:
            json.loads(inner)
            return inner
        except json.JSONDecodeError:
            pass
    return t  # let schema validation report the problem and ask again


def flatten(messages: list[dict[str, Any]], response_format: dict[str, Any] | None) -> str:
    parts = []
    for m in messages:
        role = str(m.get("role", "user")).upper()
        content = m.get("content")
        if isinstance(content, list):  # OpenAI content parts
            content = "\n".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
        parts.append(f"### {role}\n{content or ''}")
    parts.append(
        "### HOW TO ANSWER\nAnswer the request above directly in your reply. Do not run commands, do not create or edit "
        "files, and do not ask questions: there is nobody to answer them.")
    if response_format and response_format.get("type") == "json_schema":
        schema = response_format.get("json_schema", {}).get("schema", {})
        parts.append("Your whole reply must be ONE JSON object that is valid against this JSON Schema, with no prose "
                     "and no code fences:\n" + json.dumps(schema, separators=(",", ":")))
    return "\n\n".join(parts)


class AgentProvider(ModelProvider):
    """A ModelProvider whose chat() is one headless run of a coding-agent CLI."""

    def __init__(self, agent: str, model: str = "", timeout_s: float = DEFAULT_TIMEOUT_S,
                 executable: list[str] | None = None, max_retries: int = 2) -> None:
        # No super().__init__(): there is no HTTP host or API key; the agent uses its own sign-in.
        if model and not _MODEL_RE.fullmatch(model):
            raise ProviderError(f"the {agent} model name looks wrong: {model!r}")
        self.agent = agent
        self.adapter = _adapter(agent)
        if executable:
            self.adapter._exe = executable  # tests use a stand-in program
        self.model = model
        self.adapter.model = lambda: model  # type: ignore[method-assign]  # this choice, not the Control center's
        self.host = "local"
        self.fallback = None
        self.temperature = None
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.stats = ProviderStats()
        self._lock = threading.Lock()  # one agent run at a time per provider

    @property
    def label(self) -> str:
        return f"{self.adapter.label} ({self.model or 'its default model'}) [coding agent]"

    def available(self) -> tuple[bool, str]:
        if not self.adapter._executable():
            return False, f"`{self.adapter.binary}` is not installed. {self.adapter.sign_in_help}"
        return True, ""

    def command(self, cwd: Path) -> list[str]:
        """The Control center command line, narrowed to "answer in text, change nothing"."""
        cmd = self.adapter.command(cwd, full=False, hub=None)
        if self.agent == "codex" and "-s" in cmd:
            cmd[cmd.index("-s") + 1] = "read-only"
        elif self.agent == "claude" and "--tools" in cmd:
            cmd[cmd.index("--tools") + 1] = ""  # no built-in tools at all
        elif self.agent == "qoder" and "--tools" in cmd:
            cmd = cmd[:cmd.index("--tools")] + ["--tools", "Read"]  # variadic, last; the folder is empty anyway
        return cmd

    def _prepare(self, cwd: Path) -> None:
        if self.agent == "opencode":
            from zyven.orchestrator.opencode_adapter import permission_config
            cfg = permission_config()
            cfg["permission"] = {k: "deny" for k in cfg["permission"]}
            (cwd / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             response_format: dict[str, Any] | None = None, temperature: float | None = None,
             max_tokens: int | None = None) -> ChatResult:
        if tools:
            raise ProviderError(f"{self.adapter.label} runs as a compile role only; it cannot drive Zyven's tool loop "
                                "(use a chat model for the agent)")
        ok, why = self.available()
        if not ok:
            raise ProviderError(why)
        prompt = flatten(messages, response_format)
        last = ""
        with self._lock:
            for attempt in range(1, self.max_retries + 1):
                try:
                    text, totals, latency = self._run_once(prompt)
                except ProviderError as e:
                    last = str(e)
                    self.stats.retries += 1
                    continue
                self.stats.calls += 1
                self.stats.retries += attempt - 1
                self.stats.latency_s += latency
                self.stats.prompt_tokens += int(totals["in"])
                self.stats.completion_tokens += int(totals["out"])
                content = extract_json(text) if response_format else text
                return ChatResult(content=content, tool_calls=[], raw_message={"role": "assistant", "content": content},
                                  latency_s=latency, attempts=attempt, finish_reason="stop", served_by=self.label)
        self.stats.failures += 1
        self.stats.errors.append(last)
        raise ProviderError(f"{self.adapter.label} failed: {last}")

    def _run_once(self, prompt: str) -> tuple[str, dict[str, float], float]:
        from zyven.orchestrator.adapters import kill_tree
        cwd = Path(tempfile.mkdtemp(prefix=f"zyven-{self.agent}-"))
        try:
            self._prepare(cwd)
            cmd = self.command(cwd)
            if os.name == "nt" and cmd[0].lower().endswith((".cmd", ".bat")) and any(
                    re.search(r'[&|<>^%!"]', a) for a in cmd[1:]):
                raise ProviderError("a setting contains a character cmd.exe would misread")
            stdin_text = prompt
            if not self.adapter.stdin_prompt:
                cmd, stdin_text = [*cmd, prompt], ""
            env = {**os.environ, "PWD": str(cwd)}
            env.pop("OLDPWD", None)
            started = time.monotonic()
            p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            try:
                out, err = p.communicate(stdin_text, timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                kill_tree(p)
                p.communicate()
                raise ProviderError(f"no answer within {int(self.timeout_s)}s") from None
            latency = time.monotonic() - started
            replies: list[str] = []
            errors: list[str] = []
            totals = {"in": 0, "out": 0, "cost": 0.0}

            def emit(kind: str, text: str) -> None:
                if kind == "out":
                    replies.append(text)
                elif kind == "error":
                    errors.append(text)

            for line in out.splitlines():
                self.adapter.parse(line, emit, totals)
            if not replies:
                why = "; ".join(errors) or " ".join(err.split())[-300:] or f"exit code {p.returncode}"
                raise ProviderError(f"no reply ({why[:400]})")
            return replies[-1], totals, latency
        finally:
            shutil.rmtree(cwd, ignore_errors=True)


def provider_for(choice: str, env_path: str | Path = ".env") -> ModelProvider:
    """`model` (or empty) = the chat model from .env; `codex`, `claude:opus`, `agy`, `opencode:<model>`, `qoder` = an agent."""
    choice = (choice or "model").strip()
    if choice in ("", "model", "env"):
        return ModelProvider.from_env(env_path)
    name, _, model = choice.partition(":")
    if name not in AGENT_NAMES:
        raise ProviderError(f"unknown provider {choice!r}; use 'model' or one of {', '.join(AGENT_NAMES)} "
                            "(optionally with ':<model>')")
    return AgentProvider(name, model)
