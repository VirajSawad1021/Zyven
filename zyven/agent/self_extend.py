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
from zyven.agent.mcp_tools import ToolBox
from zyven.ai.provider import ModelProvider
from zyven.catalog.catalog import Catalog
from zyven.compiler.pipeline import compile_capability
from zyven.memory.skills import SkillLibrary, skill_server_spec

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


@dataclass
class ToolApprovalRequest:
    """The agent wants to run a tool from a connected service that is not read-only."""

    connection: str
    tool: str
    arguments: dict

    def as_dict(self) -> dict:
        return {"kind": "tool_call", "connection": self.connection, "tool": self.tool, "arguments": self.arguments}


ApproveFn = Callable[[ApprovalRequest | ToolApprovalRequest], Awaitable[bool]]
ConnectFn = Callable[[ToolBox, Callable[..., None], ApproveFn], Awaitable[list[str]]]


@dataclass
class SelfExtendResult:
    status: str  # DONE | FAILED | UNVERIFIED
    answer: AgentResult | None
    learned: list[str] = field(default_factory=list)  # skills compiled during this task
    reused: list[str] = field(default_factory=list)  # skills taken from the library
    events: list[dict] = field(default_factory=list)
    failed_compiles: list[str] = field(default_factory=list)  # compiled but not verified: not loaded
    rejected: list[str] = field(default_factory=list)  # approval refused: never compiled


async def run_self_extending(
    provider: ModelProvider,
    task: str,
    library: SkillLibrary,
    catalog: Catalog,
    approve: ApproveFn,
    on_event: EventFn = lambda k, d: print(f"[card] {k}: {d.get('detail', '')}", flush=True),
    system: str | None = None,
    max_tokens: int | None = 4096,
    connect: ConnectFn | None = None,
) -> SelfExtendResult:
    events: list[dict] = []
    failed_compiles: list[str] = []
    rejected: list[str] = []

    def emit(kind: str, **data) -> None:
        events.append({"event": kind, **data})
        on_event(kind, data)

    result = SelfExtendResult(status="FAILED", answer=None, events=events, failed_compiles=failed_compiles,
                              rejected=rejected)
    async with ToolBox() as tb:
        if connect is not None:  # tools from services the user connected; writes ask first
            await connect(tb, emit, approve)
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
                rejected.append(cand.title)
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
                                        skill_server_spec(compiled.spec.name, compiled.skill_dir,
                                                          Path(analysis.repo) / analysis.source_root))
            result.learned.append(compiled.spec.name)
            emit("SKILL_LEARNED", detail=f"{compiled.spec.name} ({', '.join(names)})")

        emit("RESUMED", detail=f"{len(tb.openai_tools)} tools: {', '.join(tb.tool_names)}")
        unverified = ([f"{t} (compiled but failed sandbox verification)" for t in failed_compiles]
                      + [f"{t} (compile not approved)" for t in rejected])
        agent_system = system
        if unverified:
            # Any capability the task needed but has no verified tool for: the model must not present its own
            # answer for that part as coming from the library, whether or not other skills were loaded.
            notice = (
                "NOTICE: these capabilities the task needs have NO verified tool: " + "; ".join(unverified) + ". "
                "Use the loaded tools only for what they cover. For the parts without a verified tool, say at the "
                "start of your answer that they are not verified by Zyven's sandbox and are your own unverified "
                "attempt, or decline if you cannot answer reliably. Never claim or imply that those parts come from, "
                "are backed by, or were computed by the library."
            )
            agent_system = f"{system}\n\n{notice}" if system else notice

        answer = await run_agent(provider, task, tb, system=agent_system, max_tokens=max_tokens)
        for c in answer.tool_calls:
            for s in result.learned + result.reused:
                library.record_call(s, c.name, c.ok, task)
        result.answer = answer
        if not answer.final_text or answer.error:
            result.status = "FAILED"
        elif unverified:
            result.status = "UNVERIFIED"
        else:
            result.status = "DONE"
        emit(result.status, detail=(answer.final_text or answer.error or "")[-300:],
             tool_calls=[(c.name, c.arguments) for c in answer.tool_calls])
    return result
