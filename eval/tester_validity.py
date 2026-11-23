"""How often the Tester writes a valid reference program, per model and library (issue #101).

A reference program is valid when it evaluates in the sandbox on its own case's arguments, without raising. Whether
it matches a tool is not measured: that is the Compiler's number, and no tool is built here. Everything upstream of
the Tester is held fixed: each library has one frozen capability spec in eval/tester_specs/<library>/<capability>.json.

    uv run python eval/tester_validity.py run --runs 3 --label before
    uv run python eval/tester_validity.py run --lib pyluach --lib packaging --runs 3 --label after
    uv run python eval/tester_validity.py freeze --lib packaging --capability version_specifiers
    uv run python eval/tester_validity.py freeze --lib pyluach --capability jewish_holidays \
        --entry pyluach.hebrewcal.holiday --entry pyluach.dates.GregorianDate --description "..."

`run` calls the real Tester (`tester()`, with its own follow-ups) and the real re-ask (`_reask_unusable`), then
checks every reference in the sandbox. Per run it records:
  (a) valid reference programs in the Tester's answer, out of all its cases
  (b) the same after the re-ask
  (c) tools with at least one valid case (after the re-ask), out of the spec's tools
The model is the one in .env (MODEL_* variables in the environment take precedence). Results go to
eval/results/tester-validity-<label>-<date>.{md,jsonl}. `freeze` asks the Architect for a spec once and writes it
under eval/tester_specs/; a frozen spec is never rewritten by `run`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from statistics import mean

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven import paths  # noqa: E402
from zyven.ai.provider import ModelProvider, ProviderError  # noqa: E402
from zyven.ai.roles import architect, tester  # noqa: E402
from zyven.ai.schemas import CandidateCapability, CapabilitySpec  # noqa: E402
from zyven.analysis.analyzer import analyze  # noqa: E402
from zyven.analysis.refs import RefResolver  # noqa: E402
from zyven.catalog.catalog import Catalog  # noqa: E402
from zyven.compiler.pipeline import _reask_unusable  # noqa: E402
from zyven.compiler.verify import reference_problems  # noqa: E402

SPECS = ROOT / "eval" / "tester_specs"
RESULTS = ROOT / "eval" / "results"


def checkout(cat: Catalog, name: str) -> Path:
    """The library at its pinned commit (cloned into the workspace on first use)."""
    r = next((x for x in cat.repos if x.name == name), None)
    if r is None:
        sys.exit(f"{name!r} is not in the catalog; choose from {', '.join(x.name for x in cat.repos)}")
    d = cat.checkout_dir(r)
    if not (d / ".git").exists():
        d.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", r.url, str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "--quiet", r.commit], check=True)
    return d


def frozen_specs(libs: list[str] | None) -> list[tuple[str, CapabilitySpec]]:
    out = []
    for f in sorted(SPECS.glob("*/*.json")):
        if libs and f.parent.name not in libs:
            continue
        out.append((f.parent.name, CapabilitySpec.model_validate_json(f.read_text(encoding="utf-8"))))
    return out


def measure(provider: ModelProvider, lib: str, spec: CapabilitySpec, repo: Path, run_no: int) -> dict:
    a = analyze(repo)
    roots = set(a.packages)
    work = paths.home() / "runs" / "tester-validity" / lib  # under the workspace, so the sandbox can mount it
    row = {"library": lib, "capability": spec.name, "model": provider.label, "run": run_no,
           "tools": len(spec.tools), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    started = time.monotonic()
    calls_before = provider.stats.calls
    try:
        first = tester(provider, a, spec)
    except ProviderError as e:
        return {**row, "error": f"tester: {str(e)[:300]}"}
    problems = reference_problems(first.cases, repo, a.source_root, roots, work)
    row.update(cases_first=len(first.cases), valid_first=sum(p is None for p in problems))

    def quiet(kind: str, **data) -> None:
        print(f"    [{kind}] {data.get('detail', '')}"[:200], flush=True)

    after = _reask_unusable(provider, a, spec, first, roots, quiet)
    problems = reference_problems(after.cases, repo, a.source_root, roots, work)
    valid_tools = {c.tool for c, p in zip(after.cases, problems) if p is None}
    row.update(cases_after=len(after.cases), valid_after=sum(p is None for p in problems),
               tools_with_valid=len(valid_tools & {t.name for t in spec.tools}),
               tools_without_valid=sorted({t.name for t in spec.tools} - valid_tools),
               problems=[{"tool": c.tool, "problem": p[:400]} for c, p in zip(after.cases, problems) if p],
               model_calls=provider.stats.calls - calls_before, seconds=round(time.monotonic() - started, 1))
    return row


def _share(rows: list[dict], num: str, den: str) -> str:
    vals = [r[num] / r[den] for r in rows if r.get(den)]
    if not vals:
        return "n/a"
    lo, hi = min(vals), max(vals)
    spread = f" ({lo:.0%} to {hi:.0%})" if len(vals) > 1 and hi > lo else ""
    return f"{mean(vals):.0%}{spread}"


def _tools(rows: list[dict]) -> str:
    ok = [r for r in rows if "tools_with_valid" in r]
    if not ok:
        return "n/a"
    vals = [r["tools_with_valid"] for r in ok]
    rng = f" ({min(vals)} to {max(vals)})" if min(vals) != max(vals) else ""
    return f"{mean(vals):.1f}{rng} of {ok[0]['tools']}"


def report(rows: list[dict], label: str, model: str) -> str:
    lines = [f"# Tester validity: {label} ({date.today().isoformat()})", "",
             f"- **Model:** `{model}`",
             f"- **Code:** commit `{_commit()}`",
             "- **Valid** means the reference program evaluates in the sandbox on its own case's arguments; whether it",
             "  matches a tool is not measured. Specs are frozen (`eval/tester_specs/`), so only the Tester varies.",
             "- Each cell is the mean over runs, with the range when runs differ.", "",
             "| Library | Capability | Runs | (a) valid, Tester's answer | (b) valid, after re-ask | (c) tools with a valid case |",
             "|---|---|---|---|---|---|"]
    by: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        by.setdefault((r["library"], r["capability"]), []).append(r)
    for (lib, cap), rs in by.items():
        ok = [r for r in rs if "error" not in r]
        failed = len(rs) - len(ok)
        lines.append(f"| {lib} | {cap} | {len(ok)}" + (f" (+{failed} failed)" if failed else "")
                     + f" | {_share(ok, 'valid_first', 'cases_first')} | {_share(ok, 'valid_after', 'cases_after')}"
                     f" | {_tools(ok)} |")
    errors = [r for r in rows if "error" in r]
    if errors:
        lines += ["", "## Runs that failed", ""] + [f"- {r['library']} run {r['run']}: {r['error']}" for r in errors]
    missing = [r for r in rows if r.get("tools_without_valid")]
    if missing:
        lines += ["", "## Tools left without a valid case", ""]
        for r in missing:
            first = next((p["problem"] for p in r["problems"] if p["tool"] in r["tools_without_valid"]), "no case")
            lines.append(f"- {r['library']} run {r['run']}: {', '.join(r['tools_without_valid'])}. "
                         f"First problem: `{first[:240]}`")
    return "\n".join(lines) + "\n"


def _commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def cmd_run(args) -> None:
    provider = ModelProvider.from_env(paths.env_file())
    cat = Catalog(paths.catalog_file(), paths.home())
    specs = frozen_specs(args.lib)
    if not specs:
        sys.exit("no frozen specs matched; see eval/tester_specs/ or run `freeze` first")
    stem = f"tester-validity-{args.label}-{date.today().strftime('%Y%m%d')}"
    RESULTS.mkdir(parents=True, exist_ok=True)
    jsonl = RESULTS / f"{stem}.jsonl"
    rows: list[dict] = []
    for lib, spec in specs:
        repo = checkout(cat, lib)
        for n in range(1, args.runs + 1):
            print(f"{lib}/{spec.name} run {n}/{args.runs} ({provider.label})", flush=True)
            row = measure(provider, lib, spec, repo, n)
            rows.append(row)
            with jsonl.open("a", encoding="utf-8") as f:  # appended as it goes: a long run that stops keeps its rows
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print("  " + ("error: " + row["error"] if "error" in row else
                          f"valid {row['valid_first']}/{row['cases_first']} -> {row['valid_after']}/{row['cases_after']}"
                          f", tools {row['tools_with_valid']}/{row['tools']}"), flush=True)
    (RESULTS / f"{stem}.md").write_text(report(rows, args.label, provider.label), encoding="utf-8")
    print(f"\nwrote {RESULTS / (stem + '.md')} and {jsonl}")


def cmd_freeze(args) -> None:
    out = SPECS / args.lib / f"{args.capability}.json"
    if out.exists():
        sys.exit(f"{out} exists; a frozen spec is never rewritten (delete it by hand to re-freeze)")
    provider = ModelProvider.from_env(paths.env_file())
    cat = Catalog(paths.catalog_file(), paths.home())
    repo = checkout(cat, args.lib)
    a = analyze(repo)
    r = next(x for x in cat.repos if x.name == args.lib)
    cand = next((c for c in cat.capabilities(r) if c.name == args.capability), None)
    if args.entry:
        ok, bad = RefResolver(a).resolve_all(args.entry)
        if bad:
            sys.exit(f"unknown entry points: {bad}")
        cand = CandidateCapability(name=args.capability, title=args.capability.replace("_", " ").title(),
                                   description=args.description or args.capability.replace("_", " "),
                                   entry_points=ok, why_agents_need_it="selected for the Tester measurement")
    if cand is None:
        sys.exit(f"{args.capability!r} is not a curated or scouted capability of {args.lib}; pass --entry")
    spec = architect(provider, a, cand).value
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    print(f"froze {out} ({len(spec.tools)} tools, written by {provider.label})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="measure the Tester on the frozen specs")
    r.add_argument("--lib", action="append", help="only this library (repeatable); default: every frozen spec")
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--label", default="run", help="names the result files, e.g. before or after")
    r.set_defaults(fn=cmd_run)
    f = sub.add_parser("freeze", help="ask the Architect for a library's spec once and freeze it")
    f.add_argument("--lib", required=True)
    f.add_argument("--capability", required=True)
    f.add_argument("--entry", action="append", help="entry point symbol (repeatable), when the capability is not "
                   "curated or scouted")
    f.add_argument("--description")
    f.set_defaults(fn=cmd_freeze)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
