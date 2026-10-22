"""Model provider: one OpenAI-compatible chat client for any open-weight model host.

Works with Google AI Studio (Gemma), Groq, OpenRouter, Together, or local Ollama:
switching is a change of MODEL_BASE_URL / MODEL_NAME / MODEL_API_KEY in .env.

Deliberately uses plain httpx (no proprietary vendor SDKs in the dependency tree).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Some models (e.g. Gemma 4 via AI Studio) emit their reasoning inline.
_THOUGHT_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL)
_STRAY_THOUGHT_TAG_RE = re.compile(r"</?thought>")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    pass


_PROPRIETARY = ("gemini", "gpt-", "gpt4", "o1", "o3", "o4", "claude", "command-r")


def is_proprietary(model: str) -> bool:
    """Closed models are allowed only for local experiments; reports and provenance flag them."""
    m = model.lower().split("/")[-1]
    return any(m.startswith(p) or f"/{p}" in model.lower() for p in _PROPRIETARY) and "gemma" not in m


def strip_thoughts(text: str | None) -> str:
    """Remove complete <thought>...</thought> blocks, then any unpaired tag (the text around it is kept)."""
    return _STRAY_THOUGHT_TAG_RE.sub("", _THOUGHT_RE.sub("", text or "")).strip()


def load_env(path: str | Path = ".env") -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file; real environment variables take precedence."""
    values: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    for k in list(values) + [k for k in os.environ if k.startswith(("MODEL_", "EMBED_"))]:
        if k in os.environ:
            values[k] = os.environ[k]
    return values


@dataclass
class ChatResult:
    content: str  # assistant text with inline thoughts removed
    tool_calls: list[dict[str, Any]]  # OpenAI-format tool calls, passed back verbatim
    raw_message: dict[str, Any]  # assistant message exactly as returned (for history)
    latency_s: float
    attempts: int
    finish_reason: str | None = None  # "length" means the output cap was hit
    served_by: str = ""  # host/model that produced this reply (primary or fallback)


@dataclass
class ProviderStats:
    calls: int = 0
    retries: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    failovers: int = 0  # calls the primary host could not serve and the fallback answered
    errors: list[str] = field(default_factory=list)


class ModelProvider:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        temperature: float = 0.2,
        timeout_s: float = 120.0,
        max_retries: int = 6,
        fallback: "ModelProvider | None" = None,
        cooldown_s: float = 120.0,
    ) -> None:
        if not api_key:
            raise ProviderError("MODEL_API_KEY is empty; set it in .env")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.host = httpx.URL(self.url).host
        self.model = model
        if is_proprietary(model):
            log.warning("PROPRIETARY MODEL %r in use: experiments only, not allowed for the Frogtoberfest "
                        "submission (open-weight models only).", model)
        self.fallback = fallback
        self.cooldown_s = cooldown_s
        self._down_until = 0.0  # while in the future, the primary is skipped (circuit breaker)
        self.temperature = temperature
        self.max_retries = max_retries
        self.stats = ProviderStats()
        self._client = httpx.Client(timeout=timeout_s, headers={"Authorization": f"Bearer {api_key}"})

    @property
    def label(self) -> str:
        flag = " [PROPRIETARY - experiment only]" if is_proprietary(self.model) else ""
        return f"{self.model}@{self.host}{flag}" + (f" (fallback {self.fallback.model}@{self.fallback.host})"
                                                    if self.fallback else "")

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "ModelProvider":
        """MODEL_* configures the primary host; FALLBACK_MODEL_* (optional) a backup host."""
        env = load_env(env_path)
        temperature = float(env.get("MODEL_TEMPERATURE", 0.2))
        timeout = float(env.get("MODEL_TIMEOUT_SECONDS", 120))
        fallback = None
        fb_key = env.get("FALLBACK_MODEL_API_KEY", "")
        if fb_key and not fb_key.upper().startswith("PASTE"):
            fallback = cls(
                base_url=env.get("FALLBACK_MODEL_BASE_URL", "https://openrouter.ai/api/v1"),
                model=env.get("FALLBACK_MODEL_NAME") or env.get("MODEL_NAME", ""),
                api_key=fb_key,
                temperature=temperature, timeout_s=timeout, max_retries=4,
            )
        try:
            return cls(
                base_url=env["MODEL_BASE_URL"],
                model=env["MODEL_NAME"],
                api_key=env.get("MODEL_API_KEY", ""),
                temperature=temperature,
                timeout_s=timeout,
                # With a backup available, give up on a flaky primary quickly and fail over.
                max_retries=3 if fallback else 6,
                fallback=fallback,
            )
        except KeyError as e:
            raise ProviderError(f"missing {e.args[0]} in {env_path}") from None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Primary host first; on failure (or while it is cooling down) the fallback host serves."""
        args = (messages, tools, response_format, temperature, max_tokens)
        if self.fallback and time.monotonic() < self._down_until:
            self.stats.failovers += 1
            return self.fallback.chat(*args)
        try:
            return self._chat_host(*args)
        except ProviderError as e:
            if not self.fallback:
                raise
            self._down_until = time.monotonic() + self.cooldown_s
            self.stats.failovers += 1
            log.warning("primary %s failed (%s); failing over to %s for %ss", self.host, str(e)[:80],
                        self.fallback.host, int(self.cooldown_s))
            return self.fallback.chat(*args)

    def _chat_host(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._for_host(messages),
            "temperature": self.temperature if temperature is None else temperature,
        }
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = response_format
        if max_tokens:
            body["max_tokens"] = max_tokens

        last_err = ""
        timeouts = 0
        for attempt in range(1, self.max_retries + 1):
            started = time.monotonic()
            try:
                resp = self._client.post(self.url, json=body)
            except httpx.TimeoutException as e:
                last_err = f"timeout after {time.monotonic() - started:.0f}s: {e!r}"
                timeouts += 1
                if timeouts >= 2:
                    break  # the same request stalling twice will usually stall again
            except httpx.TransportError as e:
                last_err = f"transport: {e!r}"
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    # Cline's gateway wraps the OpenAI payload in {"data": {...}, "success": true}.
                    if isinstance(data.get("data"), dict) and "choices" in data["data"]:
                        data = data["data"]
                    choices = data.get("choices")
                    if not choices:
                        last_err = f"unexpected response shape: {str(data)[:200]}"
                        break
                    choice = choices[0]
                    msg = choice["message"]
                    latency = time.monotonic() - started
                    usage = data.get("usage") or {}
                    log.info("model call ok in %.1fs (attempt %d, finish=%s, out_tokens=%s)", latency, attempt,
                             choice.get("finish_reason"), usage.get("completion_tokens"))
                    self.stats.calls += 1
                    self.stats.retries += attempt - 1
                    self.stats.latency_s += latency
                    self.stats.prompt_tokens += usage.get("prompt_tokens", 0) or 0
                    self.stats.completion_tokens += usage.get("completion_tokens", 0) or 0
                    return ChatResult(
                        content=strip_thoughts(msg.get("content")),
                        tool_calls=msg.get("tool_calls") or [],
                        raw_message=msg,
                        latency_s=latency,
                        attempts=attempt,
                        finish_reason=choice.get("finish_reason"),
                        served_by=f"{self.model}@{self.host}",
                    )
                last_err = f"HTTP {resp.status_code}: {' '.join(resp.text.split())[:200]}"
                if resp.status_code not in _RETRYABLE_STATUS:
                    break
                if resp.status_code == 429 and "spending cap" in resp.text:
                    break  # billing problem, retrying will not help
            if attempt < self.max_retries:
                delay = min(2 ** (attempt - 1), 20)
                log.warning("model call failed (%s); retry %d in %ss", last_err[:80], attempt, delay)
                time.sleep(delay)

        self.stats.failures += 1
        self.stats.errors.append(last_err)
        raise ProviderError(f"model call failed after retries: {last_err}")

    def _for_host(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop host-specific tool-call metadata (e.g. Google thought signatures) for other hosts."""
        if "googleapis" in self.host:
            return messages
        out = []
        for m in messages:
            if m.get("tool_calls"):
                m = {**m, "tool_calls": [{k: v for k, v in tc.items() if k != "extra_content"}
                                         for tc in m["tool_calls"]]}
            out.append(m)
        return out

    def generate_structured(
        self,
        messages: list[dict[str, Any]],
        schema: type[T],
        max_repairs: int = 2,
        max_tokens: int = 16384,
    ) -> T:
        """Ask for JSON matching `schema`, validate it, and feed validation errors back if needed.

        The returned object is the only thing callers consume; free text is never trusted.
        """
        json_schema = schema.model_json_schema()
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": json_schema}}
        convo = list(messages)
        last_problem = ""
        for _ in range(max_repairs + 1):
            result = self.chat(convo, response_format=fmt, max_tokens=max_tokens)
            text = _FENCE_RE.sub("", result.content).strip()
            try:
                return schema.model_validate_json(text)
            except (ValidationError, json.JSONDecodeError) as e:
                last_problem = str(e)[:800]
                # Fresh single-turn retry. Echoing the bad output back as an assistant turn makes some
                # hosted models stall, so the error is described in a new user message instead.
                convo = list(messages) + [
                    {
                        "role": "user",
                        "content": "A previous attempt at this produced JSON that failed validation:\n"
                        f"{last_problem}\nProduce the complete JSON again, valid against the schema.",
                    },
                ]
        raise ProviderError(f"structured output invalid after {max_repairs} repairs: {last_problem}")
