"""Verification gates for a compiled skill. The harness decides pass/fail from observed results only.

G1 policy      static import/builtin policy on the generated source
G2 import      server module imports inside the sandbox (no network)
G3 upstream    the source repo's relevant tests pass inside the sandbox
G4 mcp_smoke   server starts over stdio, lists every spec tool, each example call returns all declared
               fields, and calls with missing required params are rejected without crashing the server
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from zyven.ai.schemas import CapabilitySpec, DiffTests
from zyven.compiler.policy import check_adapter
from zyven.sandbox.runner import SandboxPolicy, run, run_upstream_tests

SANDBOX_IMAGE = "zyven-sandbox:py312"


@dataclass
class Gate:
    name: str
    passed: bool
    detail: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class VerificationReport:
    gates: list[Gate]
    failing_tools: dict[str, str]  # tool -> error message (input for the repair role)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "verified_for": [g.name for g in self.gates if g.passed],
                "gates": [asdict(g) for g in self.gates], "failing_tools": self.failing_tools}


def _doctest_examples(path: Path) -> int:
    """pytest counts a doctest file/module as one test; report the examples it actually checks."""
    try:
        return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                   if ln.lstrip().startswith(">>> "))
    except OSError:
        return 0


def input_variants(args: dict) -> list[dict]:
    """Natural ways a caller may write the same value; a robust tool returns the same result for each."""
    out = []
    for k, v in args.items():
        if not isinstance(v, str) or not v.strip():
            continue
        out.append({**args, k: f"  {v} "})  # stray whitespace
        compact = v.replace(" ", "")
        if len(compact) >= 8 and compact.isalnum() and sum(ch.isdigit() for ch in compact) >= 4:
            out.append({**args, k: " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))})
    return out


def smoke_plan(spec: CapabilitySpec) -> dict:
    return {"tools": {t.name: {"args": t.example_args, "returns": [r.name for r in t.returns],
                               "required": [p.name for p in t.params if p.required],
                               "variants": input_variants(t.example_args)} for t in spec.tools}}


def verify(skill_dir: Path, spec: CapabilitySpec, repo: Path, package_roots: set[str],
           run_upstream: bool = True, diff_tests: DiffTests | None = None) -> VerificationReport:
    policy = SandboxPolicy(image=SANDBOX_IMAGE, timeout_s=180)
    source = (skill_dir / "server.py").read_text(encoding="utf-8")
    gates: list[Gate] = []
    failing: dict[str, str] = {}

    pol = check_adapter(source, package_roots)
    gates.append(Gate("policy", pol.ok, "; ".join(pol.violations) or "imports and builtins within policy"))
    if not pol.ok:
        return VerificationReport(gates, {t.name: "policy: " + "; ".join(pol.violations) for t in spec.tools})

    mounts = {repo: "/src", skill_dir: "/skill"}
    env_policy = SandboxPolicy(image=SANDBOX_IMAGE, timeout_s=60, extra_env={"PYTHONPATH": "/src"})
    imp = run(["python", "-c", "import runpy; runpy.run_path('/skill/server.py', run_name='zyven_import_check')"],
              mounts, env_policy, workdir="/skill")
    gates.append(Gate("import", imp.ok, "server module imports cleanly" if imp.ok else imp.stderr.strip()[-1500:]))
    if not imp.ok:
        return VerificationReport(gates, {t.name: "import failed: " + imp.stderr.strip()[-800:] for t in spec.tools})

    if run_upstream:
        paths = list(spec.relevant_tests)
        rep = run_upstream_tests(repo, paths or None, policy)
        examples = sum(_doctest_examples(repo / p) for p in paths if p.endswith(".doctest")
                       or not Path(p).name.startswith("test"))
        ex_note = f"; includes {examples} doctest examples" if examples else ""
        gates.append(Gate("upstream_tests", rep.passed,
                          f"{rep.ran} tests ran, {rep.failures} failures, {rep.errors} errors{ex_note} "
                          f"({', '.join(paths) or 'all'})",
                          {"ran": rep.ran, "failures": rep.failures, "errors": rep.errors}))

    (skill_dir / "smoke.json").write_text(json.dumps(smoke_plan(spec), indent=1), encoding="utf-8")
    sm = run(["python", "/opt/zyven/mcp_smoke.py", "/skill/server.py", "/skill/smoke.json"], mounts, env_policy,
             workdir="/skill")
    line = next((ln for ln in sm.stdout.splitlines() if ln.startswith("ZYVEN_SMOKE_REPORT=")), None)
    report = json.loads(line.split("=", 1)[1]) if line else {"fatal": (sm.stderr or sm.stdout)[-1500:]}
    problems = []
    if not report.get("server_started"):
        problems.append(f"server did not start: {report.get('fatal', '')[:500]}")
        for t in spec.tools:
            failing[t.name] = problems[-1]
    for t in report.get("missing_tools", []):
        problems.append(f"tool {t} not listed")
        failing[t] = "tool not registered by the server"
    for c in report.get("calls", []):
        if not c.get("ok"):
            why = c.get("exception") or (f"missing return fields {c.get('missing_fields')}; output={json.dumps(c.get('output'))[:400]}"
                                         if c.get("missing_fields") else f"tool returned an error: {json.dumps(c.get('output'))[:400]}")
            problems.append(f"{c['tool']}: {why}")
            tb = f"\ntraceback (direct call in sandbox):\n{c['traceback']}" if c.get("traceback") else ""
            failing[c["tool"]] = f"example call {json.dumps(c['args'])} -> {why}{tb}"
    for c in report.get("invalid_calls", []):
        if not c.get("ok"):
            problems.append(f"{c['tool']} invalid-input check: {c.get('detail')}")
    if report.get("server_started") and not report.get("still_alive_after_calls", False):
        problems.append("server stopped responding after calls")
    weak = [p for p in report.get("robustness", []) if not p.get("ok")]
    for p in weak:
        why = (f"tool error{chr(10)}traceback (direct call in sandbox):{chr(10)}{p['traceback']}" if p.get("traceback")
               else p.get("exception") or f"different result: {json.dumps(p.get('output'))[:300]}")
        prior = failing.get(p["tool"], "")
        failing[p["tool"]] = (prior + "\n" if prior else "") + \
            f"equivalent input {json.dumps(p['args'])} must give the same result as the example call -> {why}"
    probes = len(report.get("robustness", []))
    gates.append(Gate("input_robustness", not weak and report.get("server_started", False),
                      f"{probes - len(weak)}/{probes} equivalent-input probes gave identical results"
                      + (": " + "; ".join(f"{p['tool']} {json.dumps(p['args'])}" for p in weak[:3]) if weak else ""),
                      {"probes": report.get("robustness", [])}))
    gates.append(Gate("mcp_smoke", not problems, "; ".join(problems) or
                      f"{len(report.get('calls', []))} tools called with example args; invalid input rejected",
                      report))
    if diff_tests is not None:
        gates.append(_differential_gate(skill_dir, spec, diff_tests, mounts, env_policy, package_roots, failing))
    return VerificationReport(gates, failing)


def _differential_gate(skill_dir, spec, diff_tests, mounts, env_policy, package_roots, failing) -> Gate:
    """Tool output must equal the library computed directly (Tester-written reference, adapter unseen)."""
    allowed = []
    for c in diff_tests.cases:  # reference code obeys the same static policy as adapter code
        probe = "\n".join(c.reference_imports + [f"_ = ({c.reference_expr})"])
        if check_adapter(probe, package_roots).ok:
            allowed.append(c)
    (skill_dir / "diff_tests.json").write_text(DiffTests(cases=allowed).model_dump_json(indent=1), encoding="utf-8")
    run_ = run(["python", "/opt/zyven/diff_check.py", "/skill/server.py", "/skill/diff_tests.json"], mounts,
               env_policy, workdir="/skill")
    line = next((ln for ln in run_.stdout.splitlines() if ln.startswith("ZYVEN_DIFF_REPORT=")), None)
    report = json.loads(line.split("=", 1)[1]) if line else {"fatal": (run_.stderr or run_.stdout)[-800:]}
    results = report.get("results", [])
    valid = [r for r in results if r["status"] != "invalid_reference"]
    bad = [r for r in valid if r["status"] != "match"]
    for r in bad:
        why = (f"for args {json.dumps(r['args'])}, field '{r['field']}' returned {json.dumps(r.get('got'))} but the "
               f"library itself gives {json.dumps(r.get('expected'))} (reference: {r['expr']})"
               if r["status"] == "mismatch" else f"for args {json.dumps(r['args'])} the tool raised:\n{r.get('detail')}")
        failing[r["tool"]] = (failing.get(r["tool"], "") + "\n" if r["tool"] in failing else "") + why
    untested = sorted({t.name for t in spec.tools} - {r["tool"] for r in valid})
    detail = (f"{len(valid) - len(bad)}/{len(valid)} cases match the library"
              + (f"; {len(results) - len(valid)} reference expressions invalid (ignored)" if len(results) > len(valid) else "")
              + (f"; {len(diff_tests.cases) - len(allowed)} rejected by policy" if len(allowed) < len(diff_tests.cases) else "")
              + (f"; no valid case for: {', '.join(untested)}" if untested else "")
              + ("; " + report["fatal"][:200] if report.get("fatal") else "")
              + (f"; first mismatch: {bad[0]['tool']}({json.dumps(bad[0]['args'])}).{bad[0]['field']} returned "
                 f"{json.dumps(bad[0].get('got'))}, library gives {json.dumps(bad[0].get('expected'))}"
                 if bad and bad[0]["status"] == "mismatch" else ""))
    return Gate("differential", bool(valid) and not bad and not report.get("fatal"), detail, report)
