"""Gap check and capability matching for the self-extending agent.

gap_check     : before acting, the model must state (as typed JSON) whether its current tools suffice
                and describe any missing capability. The harness acts on this; the model is never
                allowed to just guess an answer that needs a missing capability.
match_capability : pick the best entry for a gap from a list of skills or catalog capabilities, or none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from zyven.ai.provider import ModelProvider


class MissingCapability(BaseModel):
    description: str = Field(description="the capability needed, phrased generically (not the specific values)")
    inputs: str
    outputs: str
    why_needed: str


class GapCheck(BaseModel):
    plan: list[str] = Field(description="short steps to complete the task")
    can_complete_with_current_tools: bool
    missing_capabilities: list[MissingCapability] = Field(default_factory=list)


class CapabilityMatch(BaseModel):
    choice: str | None = Field(description="exact id of the best option, or null if none fits")
    confidence: Literal["high", "medium", "low"]
    reason: str


@dataclass
class Option:
    id: str
    title: str
    description: str


GAP_SYSTEM = (
    "You are the planning step of an AI agent. Decide whether the agent's CURRENT TOOLS are enough to "
    "complete the task reliably. Exact calendar conversions, lookups in domain tables, validation rules, "
    "and other facts you cannot verify are NOT reliable from memory: if the task needs one of these and no "
    "current tool provides it, report it as a missing capability. Describe each missing capability "
    "generically (e.g. 'convert Bikram Sambat dates to Gregorian'), not with the task's specific values. "
    "If the current tools are enough, return an empty missing_capabilities list."
)


def gap_check(provider: ModelProvider, task: str, tools: list[dict]) -> GapCheck:
    tool_lines = [f"- {t['function']['name']}: {t['function'].get('description', '').splitlines()[0][:160]}"
                  for t in tools] or ["(none)"]
    user = f"CURRENT TOOLS\n" + "\n".join(tool_lines) + f"\n\nTASK\n{task}"
    result = provider.generate_structured(
        [{"role": "system", "content": GAP_SYSTEM}, {"role": "user", "content": user}], GapCheck, max_tokens=4096)
    if result.missing_capabilities:
        result.can_complete_with_current_tools = False  # harness keeps the two fields consistent
    return result


def match_capability(provider: ModelProvider, need: MissingCapability, options: list[Option]) -> CapabilityMatch:
    if not options:
        return CapabilityMatch(choice=None, confidence="high", reason="no options available")
    listing = "\n".join(f"- id={o.id} | {o.title}: {o.description[:240]}" for o in options)
    system = ("Match a needed capability to the best available option. Choose only if the option clearly "
              "provides the needed inputs->outputs. Return the option id exactly, or null if none fits.")
    user = (f"NEEDED\n{need.description}\ninputs: {need.inputs}\noutputs: {need.outputs}\n\nOPTIONS\n{listing}")
    m = provider.generate_structured([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                     CapabilityMatch, max_tokens=2048)
    if m.choice is not None and m.choice not in {o.id for o in options}:
        return CapabilityMatch(choice=None, confidence="low", reason=f"model chose unknown id {m.choice!r}")
    return m
