"""Verification gates for a compiled skill. The harness decides pass/fail from observed results only.

G1 policy      static import/builtin policy on the generated source
G2 import      server module imports inside the sandbox (no network)
G3 upstream    the source repo's relevant tests pass inside the sandbox
G4 mcp_smoke   server starts over stdio, lists every spec tool, each example call returns all declared
               fields, and calls with missing required params are rejected without crashing the server
"""

from __future__ import annotations

import ast
import json
import re
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


def _text_to_value(text: str, want: type):
    """An array or object written as text. Tolerates a trailing comma or semicolon and Python-style literals."""
    t = text.strip().rstrip(",;").strip()
    for load in (json.loads, ast.literal_eval):
        try:
            value = load(t)
        except Exception:  # noqa: BLE001 - not parseable that way: try the next
            continue
        if isinstance(value, want):
            return value
    return None


def typed_args(params, args: dict) -> dict:
    """Example arguments can only hold text, numbers and booleans, but a tool may declare list or object parameters, so
    the designer writes those as JSON text. Turn each value into the type its parameter declares, so the tool is called
    the way an agent would call it (a list, not the text of a list). A value that cannot be converted is left as it was."""
    types = {p.name: p.type for p in params}
    out = {}
    for k, v in args.items():
        want = types.get(k)
        if isinstance(v, str):
            if want in ("array", "object"):
                parsed = _text_to_value(v, list if want == "array" else dict)
                v = v if parsed is None else parsed
            elif want == "integer" and re.fullmatch(r"\s*-?\d+\s*", v):
                v = int(v)
            elif want == "number" and re.fullmatch(r"\s*-?\d+(\.\d+)?\s*", v):
                v = float(v)
            elif want == "boolean" and v.strip().lower() in ("true", "false"):
                v = v.strip().lower() == "true"
        out[k] = v
    return out


def smoke_plan(spec: CapabilitySpec) -> dict:
    plan = {}
    for t in spec.tools:
        args = typed_args(t.params, t.example_args)
        plan[t.name] = {"args": args, "returns": [r.name for r in t.returns],
                        "required": [p.name for p in t.params if p.required], "variants": input_variants(args)}
    return {"tools": plan}


def unrelated_failures(failed_nodes: list[str], test_refs: dict[str, dict[str, list[str]]],
                       wrapped: set[str]) -> list[str] | None:
    """The failing tests that never call a wrapped symbol, or None when any failure might concern the wrapped code.

    A failure counts as related unless the analyzer knows the test function and none of the library symbols it calls
    is a wrapped one (or a method of one): a file that did not load, a test it cannot map, or a test that calls a
    wrapped function all keep the gate failing. In a big library (sympy) one unrelated failing test should not hide
    that every test reaching the wrapped functions passed."""
    def reaches(refs: list[str]) -> bool:
        return any(r == w or r.startswith(w + ".") or w.startswith(r + ".") for r in refs for w in wrapped)

    unrelated = []
    for node in failed_nodes:
        file, _, rest = node.partition("::")
        if not rest:  # the whole file failed (did not import, or a doctest file)
            return None
        qual = re.sub(r"\[.*\]$", "", rest).replace("::", ".")
        refs = (test_refs.get(file) or {}).get(qual)
        if refs is None or reaches(refs):
            return None
        unrelated.append(node)
    return unrelated


def verify(skill_dir: Path, spec: CapabilitySpec, repo: Path, package_roots: set[str],
           run_upstream: bool = True, diff_tests: DiffTests | None = None,
           source_root: str = ".", skip_tests: list[str] | None = None, egress=None,
           generated_per_tool: int | None = None,
           test_refs: dict[str, dict[str, list[str]]] | None = None) -> VerificationReport:
    """generated_per_tool: extra differential cases per tool built from the Tester's references (None: the default,
    0: none). Only experiments change it, e.g. the mutation test measuring what generated cases add."""
    # only the upstream-test gate uses this; big repos (e.g. sympy) need minutes, not seconds
    # with a reviewer-set host allowlist (egress), every gate runs on the egress network, as the skill will at run time
    net = {"network_name": egress.network} if egress is not None else {}
    proxy_env = egress.env() if egress is not None else {}
    policy = SandboxPolicy(image=SANDBOX_IMAGE, timeout_s=900, extra_env=dict(proxy_env), **net)
    source = (skill_dir / "server.py").read_text(encoding="utf-8")
    gates: list[Gate] = []
    failing: dict[str, str] = {}

    pol = check_adapter(source, package_roots)
    gates.append(Gate("policy", pol.ok, "; ".join(pol.violations) or "imports and builtins within policy"))
    if not pol.ok:
        return VerificationReport(gates, {t.name: "policy: " + "; ".join(pol.violations) for t in spec.tools})

    mounts = {repo: "/src", skill_dir: "/skill"}
    pythonpath = "/src" if source_root in ("", ".") else f"/src/{source_root}"
    env_policy = SandboxPolicy(image=SANDBOX_IMAGE, timeout_s=60, extra_env={"PYTHONPATH": pythonpath, **proxy_env},
                               **net)
    imp = run(["python", "-c", "import runpy; runpy.run_path('/skill/server.py', run_name='zyven_import_check')"],
              mounts, env_policy, workdir="/skill")
    gates.append(Gate("import", imp.ok, "server module imports cleanly" if imp.ok else imp.stderr.strip()[-1500:]))
    if not imp.ok:
        return VerificationReport(gates, {t.name: "import failed: " + imp.stderr.strip()[-800:] for t in spec.tools})

    if run_upstream:
        paths = list(spec.relevant_tests)
        rep = run_upstream_tests(repo, paths or None, policy, source_root=source_root, ignore=skip_tests)
        examples = sum(_doctest_examples(repo / p) for p in paths if p.endswith(".doctest")
                       or not Path(p).name.startswith("test"))
        ex_note = f"; includes {examples} doctest examples" if examples else ""
        passed, unrelated = rep.passed, None
        if not rep.passed and rep.ran > 0 and test_refs and rep.failed_nodes \
                and len(rep.failed_nodes) >= rep.failures + rep.errors:
            wrapped = set(spec.included_symbols) | {s for t in spec.tools for s in t.implementation_symbols}
            unrelated = unrelated_failures(rep.failed_nodes, test_refs, wrapped)
            reaching = sum(1 for f in paths for refs in (test_refs.get(f) or {}).values()
                           if any(r == w or r.startswith(w + ".") for r in refs for w in wrapped))
            if unrelated and reaching > 0:
                passed = True
                ex_note += (f"; {len(unrelated)} failing tests do not call the wrapped functions and are not counted:"
                            f" {', '.join(unrelated[:4])}{' ...' if len(unrelated) > 4 else ''}")
            else:
                unrelated = None
        gates.append(Gate("upstream_tests", passed,
                          f"{rep.ran} tests ran, {rep.failures} failures, {rep.errors} errors{ex_note} "
                          f"({', '.join(paths) or 'all'})",
                          {"ran": rep.ran, "failures": rep.failures, "errors": rep.errors,
                           **({"unrelated_failures": unrelated} if unrelated else {})}))

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
        gates.append(_differential_gate(skill_dir, spec, diff_tests, mounts, env_policy, package_roots, failing,
                                        generated_per_tool))
    return VerificationReport(gates, failing)


def reference_problem(c, package_roots: set[str]) -> str | None:
    """Why a Tester case's reference program cannot be used, or None if it can.

    A reference is a short program: setup statements (for example building a graph), then a last line that is the
    expression computing the value. Every line goes through the same static policy as the adapter. The pipeline uses
    this too, right after the Tester answers, so a tool left without a usable case is asked about again."""
    try:
        body = ast.parse(c.reference_expr).body
    except SyntaxError as e:
        return f"syntax error: {e.msg}"
    last = body[-1] if body else None
    if not isinstance(last, ast.Expr):
        return "the last line must be the expression that computes the value"
    if isinstance(last.value, ast.Call) and isinstance(last.value.func, ast.Name) and last.value.func.id == "print":
        # print(...) evaluates to None, so the "library value" would be null and every tool would look wrong
        return "the last line must be the value itself, not print(...) of it"
    program = [ast.unparse(st) for st in body[:-1]] + [f"_ = ({ast.unparse(last.value)})"]
    res = check_adapter("\n".join(c.reference_imports + program), package_roots)
    return None if res.ok else "; ".join(res.violations)[:110]


def _differential_gate(skill_dir, spec, diff_tests, mounts, env_policy, package_roots, failing,
                       generated_per_tool: int | None = None) -> Gate:
    """Tool output must equal the library computed directly (Tester-written reference, adapter unseen)."""
    allowed, rejected = [], []
    tools = {t.name: t for t in spec.tools}
    for c in diff_tests.cases:  # reference code obeys the same static policy as adapter code
        why = reference_problem(c, package_roots)
        if why is None:
            allowed.append(c)
        else:
            rejected.append(f"{c.tool}: {why}")
    cases = [{**c.model_dump(), "args": typed_args(tools[c.tool].params, c.args) if c.tool in tools else c.args}
             for c in allowed]
    saved = {"cases": cases, **({"generated_per_tool": generated_per_tool} if generated_per_tool is not None else {})}
    (skill_dir / "diff_tests.json").write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
    run_ = run(["python", "/opt/zyven/diff_check.py", "/skill/server.py", "/skill/diff_tests.json"], mounts,
               env_policy, workdir="/skill")
    line = next((ln for ln in run_.stdout.splitlines() if ln.startswith("ZYVEN_DIFF_REPORT=")), None)
    report = json.loads(line.split("=", 1)[1]) if line else {"fatal": (run_.stderr or run_.stdout)[-800:]}
    results = report.get("results", [])
    # generated cases the library rejects (inconclusive) or the tool refuses on purpose (tool_rejected) are not scored
    valid = [r for r in results if r["status"] not in ("invalid_reference", "inconclusive", "tool_rejected")]
    bad = [r for r in valid if r["status"] != "match"]
    own = [r for r in valid if not r.get("generated")]
    gen = [r for r in valid if r.get("generated")]
    unscored = sum(r["status"] in ("inconclusive", "tool_rejected") for r in results)
    for r in bad:
        why = ("(a generated input, not one of the Tester's cases) " if r.get("generated") else "") + (
               f"for args {json.dumps(r['args'])}, field '{r['field']}' returned {json.dumps(r.get('got'))} but the "
               f"library itself gives {json.dumps(r.get('expected'))} (reference: {r['expr']})"
               if r["status"] == "mismatch" else f"for args {json.dumps(r['args'])} the tool raised:\n{r.get('detail')}")
        failing[r["tool"]] = (failing.get(r["tool"], "") + "\n" if r["tool"] in failing else "") + why
    untested = sorted({t.name for t in spec.tools} - {r["tool"] for r in own})
    invalid = sum(r["status"] == "invalid_reference" for r in results)
    detail = (f"{sum(r['status'] == 'match' for r in own)}/{len(own)} Tester cases"
              + (f" + {sum(r['status'] == 'match' for r in gen)}/{len(gen)} generated cases" if gen else "")
              + " match the library"
              + (f" ({unscored} generated not scored: the library or the tool rejected the input)" if unscored else "")
              + (f"; {invalid} reference expressions invalid (ignored)" if invalid else "")
              + (f"; {len(rejected)} rejected by policy (e.g. {rejected[0]})" if rejected else "")
              + (f"; no valid case for: {', '.join(untested)}" if untested else "")
              + ("; " + report["fatal"][:200] if report.get("fatal") else "")
              + (f"; first mismatch: {bad[0]['tool']}({json.dumps(bad[0]['args'])}).{bad[0]['field']} returned "
                 f"{json.dumps(bad[0].get('got'))}, library gives {json.dumps(bad[0].get('expected'))}"
                 if bad and bad[0]["status"] == "mismatch" else ""))
    return Gate("differential", bool(own) and not bad and not report.get("fatal"), detail, report)
