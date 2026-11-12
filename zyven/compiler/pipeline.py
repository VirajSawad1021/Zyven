"""End-to-end compile of one capability: spec -> adapter -> verify -> bounded repair -> package.

Every step emits an event (for logs now, the task board later). The model proposes; the harness
validates references, enforces policy, runs the sandbox, and alone decides whether a skill is verified.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from zyven import __version__
from zyven.ai.provider import ModelProvider, ProviderError
from zyven.ai.roles import architect, compiler, coverage_gaps, lint_interface, repair, tester
from zyven.ai.schemas import AdapterCode, CandidateCapability, CapabilitySpec, DiffTests
from zyven.analysis.analyzer import Analysis
from zyven.compiler.build import assemble
from zyven.compiler.policy import check_adapter
from zyven.compiler.verify import VerificationReport, reference_problem
from zyven.compiler.verify import verify as _verify

EventFn = Callable[[str, dict], None]
ROLE_NAMES = {"architect", "compiler", "tester", "repair"}


@dataclass
class CompileResult:
    skill_dir: Path
    spec: CapabilitySpec
    verified: bool
    attempts: int  # compile + repair rounds
    report: VerificationReport | None
    events: list[dict] = field(default_factory=list)
    seconds: float = 0.0


def _print_event(kind: str, data: dict) -> None:
    detail = data.get("detail") or ""
    print(f"[zyven] {kind}{': ' + detail if detail else ''}", flush=True)


def compile_capability(
    provider: ModelProvider,
    a: Analysis,
    candidate: CandidateCapability | None = None,
    spec: CapabilitySpec | None = None,
    skills_root: Path = Path("skills"),
    max_repairs: int = 2,
    on_event: EventFn = _print_event,
    run_upstream: bool = True,
    roles: dict[str, ModelProvider] | None = None,
    allow_hosts: list[str] | None = None,
) -> CompileResult:
    """`provider` serves every role unless `roles` names another one for "architect", "compiler", "tester" or
    "repair" (for example a coding agent compiles and a chat model from another vendor writes the tests).

    `allow_hosts` is set by a human reviewer, never by a model: the skill may reach only these hosts, through the
    egress proxy, in every gate and later at run time (recorded in provenance as network_hosts)."""
    def verify(*args, **kw):  # every verification under the reviewer's allowlist, if there is one
        if not allow_hosts:
            return _verify(*args, **kw)
        from zyven.sandbox.egress import Egress
        with Egress(allow_hosts) as eg:
            return _verify(*args, egress=eg, **kw)

    started = time.monotonic()
    roles = roles or {}
    unknown = set(roles) - ROLE_NAMES
    if unknown:
        raise ValueError(f"unknown roles {sorted(unknown)}; use {', '.join(sorted(ROLE_NAMES))}")

    def by(role: str) -> ModelProvider:
        return roles.get(role) or provider

    events: list[dict] = []

    def emit(kind: str, **data) -> None:
        events.append({"t": round(time.monotonic() - started, 2), "event": kind, **data})
        on_event(kind, data)

    repo = Path(a.repo)
    package_roots = set(a.packages)
    provenance = {
        "repository": _remote_url(repo) or repo.name, "commit": a.commit, "license": a.license,
        "generator": f"zyven {__version__}", "model": provider.label,
        "roles": {r: by(r).label for r in sorted(ROLE_NAMES)},  # who wrote what
    }

    if spec is None:
        assert candidate is not None, "need a candidate or a spec"
        emit("architect.start", detail=f"{candidate.title} ({by('architect').label})")
        try:
            out = architect(by("architect"), a, candidate)
        except ProviderError as e:
            return _failed(emit, events, started, f"architect: {e}", candidate.name, skills_root)
        spec = out.value
        lint_warns = lint_interface(spec, a)
        if candidate.tests:  # a reviewer chose which upstream tests prove this capability
            known = {t.file for t in a.tests}
            chosen = [t for t in candidate.tests if t in known]
            if chosen:
                spec.relevant_tests = chosen
        emit("architect.done", detail=f"{len(spec.tools)} tools: {', '.join(t.name for t in spec.tools)}",
             resolved=out.resolved, dropped=out.dropped, fixes=out.fixes,
             lint_warnings=len(lint_warns))

    skill_dir = (skills_root / spec.name).resolve()
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "capability.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")

    emit("compiler.start", detail=f"writing {len(spec.tools)} tool bodies ({by('compiler').label})")
    try:
        code = compiler(by("compiler"), a, spec)
    except ProviderError as e:
        return _failed(emit, events, started, f"compiler: {e}", spec.name, skills_root, spec)
    missing = [t.name for t in spec.tools if t.name not in {i.tool for i in code.tools}]
    emit("compiler.done", detail=f"missing implementations: {missing}" if missing else "all tools implemented")

    emit("tester.start", detail="writing differential tests from the spec and library (adapter code not shown; "
                                f"{by('tester').label})")
    try:
        diff_tests = tester(by("tester"), a, spec)
        diff_tests = _reask_unusable(by("tester"), a, spec, diff_tests, package_roots, emit)
        # coverage of the cases that can actually run: a broken reference covers nothing
        gaps = coverage_gaps(spec, [c for c in diff_tests.cases if reference_problem(c, package_roots) is None])
        emit("tester.done", detail=f"{len(diff_tests.cases)} cases for {len({c.tool for c in diff_tests.cases})} tools"
             + (f"; still uncovered: " + "; ".join(f"{t}: {len(n)}" for t, n in gaps.items()) if gaps else "; full coverage"),
             coverage_gaps=gaps)
    except ProviderError as e:
        diff_tests = None
        emit("tester.error", detail=f"no differential tests: {str(e)[:200]}")

    skip_tests = [t.file for t in a.tests if t.third_party]  # cannot run offline; never collected
    report: VerificationReport | None = None
    last_checked: dict[str, str] = {}  # failing tools from the latest report whose policy gate passed
    history: list[str] = []
    attempt = 0
    for attempt in range(1, max_repairs + 2):
        (skill_dir / "server.py").write_text(assemble(spec, code, provenance), encoding="utf-8")
        emit("verify.start", detail=f"attempt {attempt}")
        report = verify(skill_dir, spec, repo, package_roots, run_upstream=run_upstream, diff_tests=diff_tests,
                        source_root=a.source_root, skip_tests=skip_tests)
        for g in report.gates:
            emit(f"gate.{g.name}", detail=("PASS " if g.passed else "FAIL ") + g.detail[:300], passed=g.passed)
        if report.gates and report.gates[0].passed:
            last_checked = dict(report.failing_tools)
        if report.passed:
            break
        if attempt > max_repairs or not report.failing_tools:
            break
        emit("repair.start", detail=f"{len(report.failing_tools)} failing tool(s): {', '.join(report.failing_tools)}")
        history += [f"attempt {attempt}: {k}: {v[:300]}" for k, v in report.failing_tools.items()]
        try:
            fixed = repair(by("repair"), a, spec, code, report.failing_tools, history[-6:])
        except ProviderError as e:
            emit("repair.error", detail=str(e)[:300])
            break
        by_name = {i.tool: i for i in fixed.tools if i.tool in report.failing_tools}
        code = AdapterCode(tools=[by_name.get(i.tool, i) for i in code.tools])
        emit("repair.done", detail=f"patched {', '.join(by_name) or 'nothing'}")

    # Partial verification: if some tools cannot be repaired, keep only the tools that pass every gate.
    dropped: dict[str, str] = {}
    if report and not report.passed and len(spec.tools) > 1:
        bad = dict(last_checked)
        for impl in code.tools:  # tools whose own code violates policy (a policy failure blocks the whole file)
            src = "\n".join(impl.imports + ["def _t():"] + ["    " + ln for ln in impl.body.splitlines()])
            pol = check_adapter(src, package_roots)
            if not pol.ok:
                bad[impl.tool] = "policy: " + "; ".join(pol.violations)
        keep = [t for t in spec.tools if t.name not in bad]
        if keep and len(keep) < len(spec.tools):
            names = {t.name for t in keep}
            sub_spec = spec.model_copy(update={"tools": keep})
            sub_code = AdapterCode(tools=[i for i in code.tools if i.tool in names])
            sub_tests = DiffTests(cases=[c for c in diff_tests.cases if c.tool in names]) if diff_tests else None
            (skill_dir / "server.py").write_text(assemble(sub_spec, sub_code, provenance), encoding="utf-8")
            emit("verify.partial", detail=f"re-verifying {len(keep)}/{len(spec.tools)} tools without: {', '.join(bad)}")
            sub = verify(skill_dir, sub_spec, repo, package_roots, run_upstream=run_upstream, diff_tests=sub_tests,
                         source_root=a.source_root, skip_tests=skip_tests)
            for g in sub.gates:
                emit(f"gate.{g.name}", detail=("PASS " if g.passed else "FAIL ") + g.detail[:300], passed=g.passed)
            if sub.passed:
                dropped = {k: v[:300] for k, v in bad.items()}
                spec, code, report = sub_spec, sub_code, sub
                (skill_dir / "capability.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")

    verified = bool(report and report.passed)
    seconds = round(time.monotonic() - started, 1)
    (skill_dir / "adapter-code.json").write_text(code.model_dump_json(indent=1), encoding="utf-8")
    (skill_dir / "provenance.json").write_text(json.dumps({
        **provenance, "capability": spec.name, "mode": spec.mode, "included_symbols": spec.included_symbols,
        "source_checkout": str((repo / a.source_root).resolve()),  # wrap mode: importable source at runtime
        "source_root": a.source_root,
        "network_hosts": list(allow_hosts or []),  # set by a reviewer; enforced at run time by the egress proxy
        "generated_files": ["server.py"], "compile_seconds": seconds, "attempts": attempt,
        "dropped_tools": dropped,  # tools that could not be verified and are NOT in the package
        "model_calls": sum(p.stats.calls for p in {id(by(r)): by(r) for r in ROLE_NAMES}.values()),
        "lint_warnings": len(lint_interface(spec, a)),  # interface lint warnings on the final spec; use to track quality
    }, indent=1), encoding="utf-8")
    (skill_dir / "validation-report.json").write_text(json.dumps(report.to_dict() if report else {}, indent=1,
                                                                 ensure_ascii=False), encoding="utf-8")
    (skill_dir / "events.json").write_text(json.dumps(events, indent=1, ensure_ascii=False), encoding="utf-8")
    emit("done", detail=f"{'VERIFIED' if verified else 'NOT VERIFIED'} after {attempt} attempt(s) in {seconds}s"
         + (f" ({len(spec.tools)} tools; dropped unverifiable: {', '.join(dropped)})" if dropped else ""),
         verified=verified)
    return CompileResult(skill_dir, spec, verified, attempt, report, events, seconds)


def _reask_unusable(provider, a, spec, diff_tests, package_roots, emit):
    """Ask the Tester once more for every tool whose cases all fail the sandbox's own reference checks (a syntax
    error, a last line that is not the value, print(...), a policy violation), quoting why. Without this, such a tool
    has no differential check at all: a mutation test showed one losing every case to syntax errors."""
    problems: dict[str, list[str]] = {}
    usable = []
    for c in diff_tests.cases:
        why = reference_problem(c, package_roots)
        if why is None:
            usable.append(c)
        else:
            problems.setdefault(c.tool, []).append(why)
    # Gaps are judged on the cases that can run: a case that set an optional parameter but has a syntax error covers
    # nothing (a mutation in sort_versions' optional branch survived exactly that way).
    gaps = coverage_gaps(spec, usable)
    lacking = [t for t in spec.tools if t.name in gaps]
    if not lacking:
        return diff_tests
    emit("tester.retry", detail=f"{len(lacking)} tool(s) need more runnable cases: {', '.join(t.name for t in lacking)}")
    lines = []
    for t in lacking:
        why = "; ".join(sorted(set(problems.get(t.name, []))))[:400]
        lines.append(f"- {t.name}: still needed: {'; '.join(gaps[t.name])}"
                     + (f". Earlier cases were rejected: {why}" if why else ""))
    feedback = ("WRITE NEW TEST CASES FOR THESE TOOLS. Earlier cases left these gaps or could not be used:\n"
                + "\n".join(lines))
    try:
        extra = tester(provider, a, spec.model_copy(update={"tools": lacking}), feedback=feedback, followups=False)
    except ProviderError as e:
        emit("tester.error", detail=f"re-ask failed: {str(e)[:200]}")
        return diff_tests
    names = {t.name for t in lacking}
    added = [c for c in extra.cases if c.tool in names and reference_problem(c, package_roots) is None]
    emit("tester.retry.done", detail=f"{len(added)} usable case(s) added for "
         f"{len({c.tool for c in added})}/{len(lacking)} tool(s)")
    return DiffTests(cases=list(diff_tests.cases) + added)


def _failed(emit, events, started, reason: str, name: str, skills_root: Path,
            spec: CapabilitySpec | None = None) -> CompileResult:
    """A model/host failure ends the compile cleanly as NOT VERIFIED (nothing is loaded or kept)."""
    seconds = round(time.monotonic() - started, 1)
    emit("done", detail=f"NOT VERIFIED: {reason[:240]}", verified=False)
    placeholder = spec or CapabilitySpec(name=name, title=name, summary="", tools=[], included_symbols=[],
                                         relevant_tests=[])
    # Keep the evidence: without it a failed run (a model quota, a timeout) left nothing to diagnose. This folder has no
    # server.py, so the skill library never mistakes it for a skill.
    where = (skills_root / f"_failed_{name}").resolve()
    try:
        where.mkdir(parents=True, exist_ok=True)
        (where / "events.json").write_text(json.dumps(events, indent=1, ensure_ascii=False), encoding="utf-8")
        (where / "failure.json").write_text(json.dumps({"capability": name, "reason": reason, "seconds": seconds},
                                                       indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # diagnostics are best effort; the result already says NOT VERIFIED
    return CompileResult(where, placeholder, False, 0, None, events, seconds)


def _remote_url(repo: Path) -> str | None:
    cfg = repo / ".git" / "config"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("url ="):
                return line.split("=", 1)[1].strip()
    return None
