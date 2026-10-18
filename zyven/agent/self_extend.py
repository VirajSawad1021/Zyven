"""Self-extending agent: notice a missing capability, find it, get approval, compile, verify, resume.

Card lifecycle (events emitted at each step):
RUNNING -> GAP_CHECK -> (skill library hit -> RESUMED)
                     -> SEARCHING -> NEEDS_APPROVAL -> COMPILING -> RESUMED -> DONE | FAILED
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from zyven.agent.gap import CapabilityMatch, MissingCapability, gap_check, match_capability
from zyven.agent.loop import AgentResult, run_agent
from zyven.agent.mcp_tools import MCPServerSpec, ToolBox
from zyven.ai.provider import ModelProvider
from zyven.catalog.catalog import Catalog
from zyven.compiler.pipeline import compile_capability
from zyven.memory.skills import SkillLibrary

EventFn = Callable[[str, dict], None]


@dataclass
class ApprovalRequest:
    need: MissingCapability
    option_id: str
    repo_url: str
    commit: str
    license: str
    capability_title: str
    capability_description: str
    match_reason: str


ApproveFn = Callable[[ApprovalRequest], Awaitable[bool]]


@dataclass
class SelfExtendResult:
    status: str  # DONE | FAILED | UNVERIFIED
    answer: AgentResult | None
    learned: list[str] = field(default_factory=list)  # skills compiled during this task
    reused: list[str] = field(default_factory=list)  # skills taken from the library
    events: list[dict] = field(default_factory=list)
    failed_compiles: list[str] = field(default_factory=list)


async def run_self_extending(
    provider: ModelProvider,
    task: str,
    library: SkillLibrary,
    catalog: Catalog,
    approve: ApproveFn,
    on_event: EventFn = lambda k, d: print(f"[card] {k}: {d.get('detail', '')}", flush=True),
    system: str | None = None,
    max_tokens: int | None = 4096,
) -> SelfExtendResult:
    events: list[dict] = []
    failed_compiles: list[str] = []

    def emit(kind: str, **data) -> None:
        events.append({"event": kind, **data})
        on_event(kind, data)

    result = SelfExtendResult(status="FAILED", answer=None, events=events, failed_compiles=failed_compiles)
    async with ToolBox() as tb:
        emit("RUNNING", detail=f"{len(tb.openai_tools)} tools loaded")
        gap = await asyncio.to_thread(gap_check, provider, task, tb.openai_tools)
        emit("GAP_CHECK", detail="tools sufficient" if not gap.missing_capabilities else
             "; ".join(m.description for m in gap.missing_capabilities), plan=gap.plan)

        for need in gap.missing_capabilities:
            # 1) Already learned? Search the skill library first.
            skills = library.list()
            m: CapabilityMatch = await asyncio.to_thread(match_capability, provider, need, [s.option() for s in skills])
            if m.choice:
                skill = library.get(m.choice)
                names = await tb.add_server(skill.server_spec())
                result.reused.append(skill.name)
                emit("SKILL_REUSED", detail=f"{skill.name} ({', '.join(names)})", reason=m.reason)
                continue

            # 2) Search the curated catalog.
            emit("SEARCHING", detail=need.description)
            m = await asyncio.to_thread(match_capability, provider, need, catalog.options())
            if not m.choice:
                emit("NO_MATCH", detail=m.reason)
                continue
            repo, cand, analysis = catalog.resolve(m.choice)

            # 3) Human approval before any outside code is compiled or run.
            req = ApprovalRequest(need, m.choice, repo.url, repo.commit, repo.license, cand.title,
                                  cand.description, m.reason)
            emit("NEEDS_APPROVAL", detail=f"{cand.title} from {repo.url} @ {repo.commit[:7]} ({repo.license})",
                 request=req.__dict__ | {"need": need.model_dump()})
            if not await approve(req):
                emit("REJECTED", detail=cand.title)
                continue

            # 4) Compile + verify in the sandbox.
            emit("COMPILING", detail=cand.title)
            compiled = await asyncio.to_thread(
                compile_capability, provider, analysis, cand, None, library.root, 2,
                lambda k, d: emit(f"compile.{k}", **d))
            if not compiled.verified:
                emit("COMPILE_FAILED", detail=f"{cand.title}: not verified; skill not loaded")
                failed_compiles.append(cand.title)
                continue
            learned = library.get(compiled.spec.name)
            names = await tb.add_server(learned.server_spec() if learned else
                                        MCPServerSpec.python_script(compiled.spec.name, compiled.skill_dir / "server.py"))
            result.learned.append(compiled.spec.name)
            emit("SKILL_LEARNED", detail=f"{compiled.spec.name} ({', '.join(names)})")

        emit("RESUMED", detail=f"{len(tb.openai_tools)} tools: {', '.join(tb.tool_names)}")
        agent_system = system
        if failed_compiles and not (result.learned or result.reused):
            failed_str = ", ".join(failed_compiles)
            unverified_prompt = (
                f"\n\nCRITICAL NOTICE: Capability compilation and verification FAILED for: {failed_str}. "
                "These tools were NOT loaded and are NOT available to you. "
                "Zyven guarantees that unverified library code is never trusted. "
                "You must state clearly at the very beginning of your response that this capability could not be verified by Zyven's sandbox, "
                "and that any following answer is your own unverified attempt without tool assistance (or decline if you cannot answer reliably). "
                "You must NEVER claim or imply that your answer comes from, is backed by, or was computed by the library."
            )
            agent_system = (system or (
                "You are a helpful assistant that completes the user's task using your tools when they apply. "
                "Report tool results faithfully; do not recompute what a tool already returned. Be concise."
            )) + unverified_prompt

        answer = await run_agent(provider, task, tb, system=agent_system, max_tokens=max_tokens)
        for c in answer.tool_calls:
            for s in result.learned + result.reused:
                library.record_call(s, c.name, c.ok, task)
        result.answer = answer
        result.failed_compiles = failed_compiles
        if not answer.final_text or answer.error:
            result.status = "FAILED"
        elif failed_compiles and not (result.learned or result.reused):
            result.status = "UNVERIFIED"
        else:
            result.status = "DONE"
        emit(result.status, detail=(answer.final_text or answer.error or "")[-300:],
             tool_calls=[(c.name, c.arguments) for c in answer.tool_calls])
    return result

