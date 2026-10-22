"""Minimal tool-using agent loop on top of ModelProvider + MCP ToolBox."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from zyven.agent.mcp_tools import ToolBox
from zyven.ai.provider import ModelProvider, ProviderError


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    ok: bool
    output: str


@dataclass
class AgentResult:
    final_text: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    seconds: float = 0.0
    error: str | None = None
    truncated: bool = False  # model hit the output cap before answering
    recovered: bool = False  # a budget-exhausted reply triggered the one-time "answer now" retry
    prompt_tokens: int = 0
    completion_tokens: int = 0
    served_by: set[str] = field(default_factory=set)


async def run_agent(
    provider: ModelProvider,
    task: str,
    toolbox: ToolBox | None = None,
    system: str | None = None,
    max_steps: int = 6,
    max_tokens: int | None = None,
    seed: int | None = None,
) -> AgentResult:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": task})
    result = AgentResult(final_text="")
    started = time.monotonic()

    for step in range(1, max_steps + 1):
        result.steps = step
        tools = toolbox.openai_tools if toolbox and toolbox.openai_tools else None
        try:
            reply = await asyncio.to_thread(provider.chat, messages, tools, None, None, max_tokens, seed)
        except ProviderError as e:
            result.error = str(e)
            break

        result.prompt_tokens += reply.prompt_tokens
        result.completion_tokens += reply.completion_tokens
        if reply.served_by:
            result.served_by.add(reply.served_by)

        if not reply.tool_calls:
            if reply.finish_reason == "length" and not reply.content and not result.recovered:
                # Small models sometimes loop while reasoning and exhaust the budget before answering.
                # Give exactly one more chance with a direct instruction; applied in every condition.
                result.recovered = True
                messages.append({"role": "user", "content": "You ran out of space before answering. "
                                 "Do not deliberate further. Reply now with your final answer only."})
                continue
            result.final_text = reply.content
            result.truncated = reply.finish_reason == "length"
            break

        # Pass the assistant message back verbatim (some hosts require their tool-call metadata).
        messages.append({k: v for k, v in reply.raw_message.items() if v is not None})
        for call in reply.tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
                ok, output = False, "Arguments were not valid JSON."
            else:
                ok, output = await toolbox.call(name, args) if toolbox else (False, "No tools available.")
            result.tool_calls.append(ToolCallRecord(name=name, arguments=args, ok=ok, output=output))
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": output})
    else:
        result.error = f"no final answer after {max_steps} steps"

    result.seconds = time.monotonic() - started
    return result
