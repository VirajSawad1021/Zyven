"""Mutation test of the verification gates: break verified skills on purpose and count what the gates catch.

For each verified skill, every tool body is parsed and small, realistic bugs are injected one at a time (a mutant):
a flipped comparison, an arithmetic swap, an off-by-one constant, a negated condition, swapped call arguments, a
dropped statement, a wrong return value. Each mutant is assembled with the normal harness and run through the gates
with the skill's own saved differential cases. A mutant is *killed* if any gate fails, and the report says which.

    uv run python eval/mutation_test.py skills/graph_algorithms --max 40
    uv run python eval/mutation_test.py path/to/library --max 25 --seed 1

No model is called. The upstream-tests gate is skipped: it runs the library's own tests, not the adapter, so it can
never catch an adapter bug (pass --with-upstream to include it anyway). A surviving mutant is either a gap in the
gates or an *equivalent* mutant (one that changes nothing observable); the report lists survivors so each can be read.
Results go to eval/results/mutation-<time>.{json,md}.
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import random
import re
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.ai.schemas import AdapterCode, CapabilitySpec, DiffCase, DiffTests  # noqa: E402
from zyven.compiler.build import assemble  # noqa: E402

CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
            ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.Div: ast.Mult, ast.FloorDiv: ast.Mult,
            ast.Mod: ast.FloorDiv}
BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass
class Mutant:
    skill: str
    tool: str
    operator: str
    where: str          # line of the original body and what changed
    killed_by: str = ""  # first failing gate, or "" if it survived
    detail: str = ""
    failed_gates: list[str] | None = None  # every gate that failed (later gates still run after a smoke failure)


def _sites(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """Every place one operator can change, as (operator name, node)."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            out += [("compare", n)] if any(type(op) in CMP_SWAP for op in n.ops) else []
        elif isinstance(n, ast.BinOp) and type(n.op) in BIN_SWAP:
            out.append(("arithmetic", n))
        elif isinstance(n, ast.BoolOp) and type(n.op) in BOOL_SWAP:
            out.append(("boolean", n))
        elif isinstance(n, ast.Constant) and isinstance(n.value, bool):
            out.append(("flip_bool", n))
        elif isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool):
            out.append(("off_by_one", n))
        elif isinstance(n, (ast.If, ast.While)) and not isinstance(n.test, ast.UnaryOp):
            out.append(("negate_condition", n))
        elif isinstance(n, ast.Call) and len(n.args) >= 2:
            out.append(("swap_args", n))
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Dict) and len(n.value.keys) >= 1:
            out.append(("drop_return_field", n))
    for body_owner in [n for n in ast.walk(tree) if hasattr(n, "body") and isinstance(getattr(n, "body"), list)]:
        for i, st in enumerate(body_owner.body):
            if isinstance(st, (ast.Assign, ast.AugAssign, ast.Expr)) and len(body_owner.body) > 1:
                out.append(("drop_statement", (body_owner, i)))
    return out


def _apply(op: str, node) -> str:
    """Mutate `node` in place; returns a short description."""
    if op == "compare":
        i = next(i for i, o in enumerate(node.ops) if type(o) in CMP_SWAP)
        old = type(node.ops[i]).__name__
        node.ops[i] = CMP_SWAP[type(node.ops[i])]()
        return f"{old} -> {type(node.ops[i]).__name__}"
    if op == "arithmetic":
        old = type(node.op).__name__
        node.op = BIN_SWAP[type(node.op)]()
        return f"{old} -> {type(node.op).__name__}"
    if op == "boolean":
        old = type(node.op).__name__
        node.op = BOOL_SWAP[type(node.op)]()
        return f"{old} -> {type(node.op).__name__}"
    if op == "flip_bool":
        node.value = not node.value
        return f"{not node.value} -> {node.value}"
    if op == "off_by_one":
        node.value = node.value + 1
        return f"{node.value - 1} -> {node.value}"
    if op == "negate_condition":
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        return "condition negated"
    if op == "swap_args":
        node.args[0], node.args[1] = node.args[1], node.args[0]
        return "first two arguments swapped"
    if op == "drop_return_field":
        key = node.value.keys.pop()
        node.value.values.pop()
        return f"return field {ast.unparse(key) if key is not None else '**'} dropped"
    if op == "drop_statement":
        owner, i = node
        gone = owner.body.pop(i)
        return f"statement dropped: {ast.unparse(gone)[:60]}"
    raise ValueError(op)


def mutants_for(body: str, rng: random.Random, limit: int) -> list[tuple[str, str, str]]:
    """Up to `limit` distinct mutated bodies: (operator, description, new body)."""
    tree = ast.parse(body)
    sites = _sites(tree)
    rng.shuffle(sites)
    out, seen = [], {ast.unparse(tree)}
    for op, _ in sites:
        if len(out) >= limit:
            break
        t2 = copy.deepcopy(tree)
        # find the same site in the copy by walking both trees in the same order
        node2 = _same_site(tree, t2, op, _)
        if node2 is None:
            continue
        try:
            desc = _apply(op, node2)
            text = ast.unparse(t2)
            compile(text, "<mutant>", "exec")
        except Exception:  # noqa: BLE001  an operator that does not fit this site
            continue
        if text not in seen:
            seen.add(text)
            line = getattr(_ if not isinstance(_, tuple) else _[0].body[_[1]], "lineno", "?")
            out.append((op, f"line {line}: {desc}", text))
    return out


def _same_site(orig: ast.AST, clone: ast.AST, op: str, node):
    a, b = list(ast.walk(orig)), list(ast.walk(clone))
    if isinstance(node, tuple):  # (owner, index)
        owner, i = node
        return (b[a.index(owner)], i) if owner in a else None
    return b[a.index(node)] if node in a else None


def _wrap(body: str) -> str:  # tool bodies use `return` at top level; parse them inside a function
    return "def _t():\n" + "\n".join("    " + ln for ln in body.splitlines())


def _unwrap(text: str) -> str:
    fn = ast.parse(text).body[0]
    return "\n".join(ast.unparse(st) for st in fn.body)


CALIBRATE = False
CALIBRATION_LOG: list[str] = []


def _same_args(case_args: dict, reported: dict) -> bool:
    """The gate reports typed arguments (lists), the saved case may hold them as JSON text."""
    if set(case_args) != set(reported):
        return False
    for k, v in case_args.items():
        r = reported[k]
        if v == r:
            continue
        if isinstance(v, str):
            try:
                if json.loads(v) == r:
                    continue
            except ValueError:
                pass
        return False
    return True


def run_skill(skill_dir: Path, per_tool: int, rng: random.Random, with_upstream: bool) -> list[Mutant]:
    from zyven.analysis.analyzer import analyze
    from zyven.compiler.verify import verify

    spec = CapabilitySpec.model_validate_json((skill_dir / "capability.json").read_text(encoding="utf-8"))
    code = AdapterCode.model_validate_json((skill_dir / "adapter-code.json").read_text(encoding="utf-8"))
    prov = json.loads((skill_dir / "provenance.json").read_text(encoding="utf-8"))
    cases = json.loads((skill_dir / "diff_tests.json").read_text(encoding="utf-8")).get("cases") or []
    diff = DiffTests.model_construct(cases=[DiffCase.model_construct(**c) for c in cases])
    src, root = Path(prov["source_checkout"]), prov.get("source_root") or "."
    repo = src if root in ("", ".") else Path(*src.parts[:len(src.parts) - len(Path(root).parts)])
    a = analyze(repo, source_root=None if root in ("", ".") else root)

    def gates_for(bodies):
        import warnings
        work = Path(tempfile.mkdtemp(prefix="zyven-mutant-"))
        try:
            for f in skill_dir.iterdir():
                if f.is_file():
                    shutil.copy(f, work / f.name)
            (work / "server.py").write_text(assemble(spec, AdapterCode(tools=bodies), prov), encoding="utf-8")
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*serializ", category=UserWarning)
                return verify(work, spec, repo, set(a.packages), run_upstream=with_upstream, diff_tests=diff,
                              source_root=a.source_root, skip_tests=[t.file for t in a.tests if t.third_party])
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # Control: the unmutated skill through exactly this path must pass, or every "kill" below would be an artifact.
    # Bodies go through the same parse/unparse round trip as the mutants.
    control = gates_for([i.model_copy(update={"body": _unwrap(_wrap(i.body))}) for i in code.tools])
    calibrated: list[str] = []
    while CALIBRATE and not control.passed and len(calibrated) < 10:
        # Standard mutation-testing rule: a test must pass on the original program. Only differential mismatches are
        # calibrated away (a Tester case whose expected value is wrong); any other failing gate still aborts.
        failing = [g.name for g in control.gates if not g.passed]
        if failing != ["differential"]:
            break
        drop = []
        for msg in control.failing_tools.values():
            mt = re.match(r"for args (\{.*?\}), field '([^']+)' returned", msg)
            if mt:
                drop.append((json.loads(mt.group(1)), mt.group(2)))
        if not drop:
            break
        before = len(diff.cases)
        diff.cases = [c for c in diff.cases if not any(_same_args(c.args, a_) and c.field == f for a_, f in drop)]
        if len(diff.cases) == before:
            break
        calibrated += [f"{f} for {json.dumps(a_)[:80]}" for a_, f in drop]
        control = gates_for([i.model_copy(update={"body": _unwrap(_wrap(i.body))}) for i in code.tools])
    if calibrated:
        print(f"  calibration: dropped {len(calibrated)} case(s) that fail on the UNMUTATED skill: {calibrated}",
              flush=True)
        CALIBRATION_LOG.extend(f"{skill_dir.name}: {c}" for c in calibrated)
    if not control.passed:
        failed = "; ".join(f"{g.name}: {g.detail[:120]}" for g in control.gates if not g.passed)
        raise SystemExit(f"{skill_dir.name}: the UNMUTATED skill fails here ({failed}); results would be meaningless")
    print(f"  control (unmutated): all {len(control.gates)} gates pass", flush=True)
    out: list[Mutant] = []
    for impl in code.tools:
        for op, where, mutated in mutants_for(_wrap(impl.body), rng, per_tool):
            m = Mutant(skill_dir.name, impl.tool, op, where)
            try:
                bodies = [i.model_copy(update={"body": _unwrap(mutated)}) if i.tool == impl.tool
                          else i.model_copy(update={"body": _unwrap(_wrap(i.body))}) for i in code.tools]
                rep = gates_for(bodies)
                infra = next((g for g in rep.gates if not g.passed and _infrastructure(g.detail)), None)
                if infra:  # the sandbox itself broke (Docker stopped): not a kill, and nothing after it counts
                    raise SystemExit(f"{m.tool} {m.operator}: Docker failed during the run ({infra.detail[:160]}). "
                                     "Stopped; no result written. Start Docker and run again.")
                bad = next((g for g in rep.gates if not g.passed), None)
                m.failed_gates = [g.name for g in rep.gates if not g.passed]
                m.killed_by = bad.name if bad else ""
                m.detail = (bad.detail[:160] if bad else "all gates passed")
            except Exception as e:  # noqa: BLE001  a harness error is recorded, never counted as a kill
                m.killed_by, m.detail = "", f"ERROR {type(e).__name__}: {str(e)[:140]}"
            out.append(m)
            print(f"  {'KILLED by ' + m.killed_by if m.killed_by else 'SURVIVED':28} {m.tool}: {m.operator} ({m.where})",
                  flush=True)
    # Control again at the end: if the unmutated skill no longer passes, something changed under the run.
    again = gates_for([i.model_copy(update={"body": _unwrap(_wrap(i.body))}) for i in code.tools])
    if not again.passed:
        raise SystemExit(f"{skill_dir.name}: the unmutated skill fails at the END of the run; its results are discarded")
    print("  control again (end): all gates pass", flush=True)
    return out


INFRA_MARKERS = ("error during connect", "dockerDesktopLinuxEngine", "Cannot connect to the Docker daemon",
                 "docker: command not found", "is the docker daemon running")


def _infrastructure(detail: str) -> bool:
    return any(s.lower() in (detail or "").lower() for s in INFRA_MARKERS)


def report(muts: list[Mutant], args, seconds: float) -> tuple[dict, str]:
    errors = [m for m in muts if m.detail.startswith("ERROR")]
    scored = [m for m in muts if not m.detail.startswith("ERROR")]
    killed = [m for m in scored if m.killed_by]
    by_gate: dict[str, int] = {}
    by_op: dict[str, list[int]] = {}
    for m in scored:
        if m.killed_by:
            by_gate[m.killed_by] = by_gate.get(m.killed_by, 0) + 1
        k = by_op.setdefault(m.operator, [0, 0])
        k[0] += bool(m.killed_by)
        k[1] += 1
    score = len(killed) / len(scored) if scored else 0.0
    # Would each gate alone have caught the mutant? (a gate that stops verification early hides later ones)
    alone: dict[str, int] = {}
    for m in scored:
        for g in m.failed_gates or []:
            alone[g] = alone.get(g, 0) + 1
    data = {"mutants": len(scored), "killed": len(killed), "score": round(score, 3), "errors": len(errors),
            "by_gate": by_gate, "failed_at_all": alone, "by_operator": {k: {"killed": v[0], "total": v[1]} for k, v in by_op.items()},
            "upstream_gate": args.with_upstream, "seed": args.seed, "seconds": round(seconds),
            "skills": sorted({m.skill for m in muts}), "calibrated": CALIBRATION_LOG,
            "results": [asdict(m) for m in muts]}
    md = [f"# Mutation test of the gates ({time.strftime('%Y-%m-%d')})", "",
          f"**{len(killed)}/{len(scored)} mutants killed ({score:.0%})** across {', '.join(data['skills'])}; "
          f"seed {args.seed}; upstream-tests gate {'included' if args.with_upstream else 'skipped (it tests the library, not the adapter)'}"
          f"; {round(seconds / 60)} min.", "",
          "| Gate | First to fail | Failed at all |", "|---|---|---|"] + \
        [f"| {g} | {by_gate.get(g, 0)} | {alone.get(g, 0)} |" for g in sorted(set(by_gate) | set(alone), key=lambda x: -alone.get(x, 0))] + \
        ["", "\"Failed at all\" counts every gate that failed for a mutant. Policy and import failures stop verification, "
             "so later gates did not run for those."]
    md += ["", "| Operator | Killed / total |", "|---|---|"] + [f"| {k} | {v[0]}/{v[1]} |" for k, v in sorted(by_op.items())]
    surv = [m for m in scored if not m.killed_by]
    if surv:
        md += ["", "## Survivors (a gap in the gates, or an equivalent mutant: read each)", ""]
        md += [f"- `{m.skill}.{m.tool}` {m.operator}: {m.where}" for m in surv]
    if CALIBRATION_LOG:
        md += ["", f"Calibration (--calibrate): {len(CALIBRATION_LOG)} Tester case(s) failed on the UNMUTATED "
               "skill and were dropped before the mutants ran:"] + [f"- {c}" for c in CALIBRATION_LOG]
    if errors:
        md += ["", f"{len(errors)} mutant(s) could not be run (harness errors, not counted):"]
        md += [f"- `{m.tool}` {m.operator}: {m.detail}" for m in errors[:10]]
    return data, "\n".join(md) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path, help="skill folders or libraries")
    ap.add_argument("--max", type=int, default=8, help="mutants per tool")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--with-upstream", action="store_true", help="also run the upstream-tests gate (slow, cannot kill)")
    ap.add_argument("--calibrate", action="store_true", help="drop Tester cases that fail on the unmutated skill "
                    "(reported); without it such a skill aborts the run")
    ap.add_argument("--out", type=Path, default=ROOT / "eval" / "results")
    args = ap.parse_args()
    global CALIBRATE
    CALIBRATE = args.calibrate
    rng = random.Random(args.seed)
    skills = []
    for p in args.paths:
        skills += [p] if (p / "adapter-code.json").exists() else sorted(d for d in p.iterdir() if (d / "adapter-code.json").exists())
    started = time.monotonic()
    muts: list[Mutant] = []
    for s in skills:
        print(f"{s.name}:", flush=True)
        muts += run_skill(s, args.max, rng, args.with_upstream)
    data, md = report(muts, args, time.monotonic() - started)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (args.out / f"mutation-{stamp}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (args.out / f"mutation-{stamp}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
