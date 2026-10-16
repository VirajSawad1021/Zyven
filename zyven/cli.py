"""zyven command line.

  zyven analyze <repo>                         deterministic analysis + rules-only baseline
  zyven scout   <repo>                         AI: list user-level capabilities
  zyven compile <repo> --capability <name>     AI: spec -> adapter -> sandbox verify -> repair -> package
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from zyven.ai.provider import ModelProvider
from zyven.ai.roles import scout
from zyven.ai.schemas import ScoutResult
from zyven.analysis.analyzer import analyze
from zyven.analysis.miner import baseline_candidates
from zyven.compiler.pipeline import compile_capability


def _workdir(repo: Path) -> Path:
    d = Path("workspace") / "runs" / repo.resolve().name
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_analyze(args) -> None:
    a = analyze(args.repo)
    out = _workdir(Path(args.repo)) / "analysis.json"
    out.write_text(json.dumps(a.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
    pub = [s for s in a.symbols if s.is_public and not s.file.startswith("tests")]
    print(f"{Path(a.repo).name} @ {str(a.commit)[:7]} · license {a.license} · {len(a.modules)} modules · "
          f"{len(pub)} public symbols · {sum(t.test_count for t in a.tests)} tests")
    print("\nRules-only baseline candidates:")
    for c in baseline_candidates(a):
        print(f"  {c.score:5.2f}  {c.module:40} {', '.join(e.rsplit('.', 1)[-1] for e in c.entry_points)}")
    print(f"\nwrote {out}")


def cmd_scout(args) -> None:
    a = analyze(args.repo)
    p = ModelProvider.from_env(args.env)
    res = scout(p, a)
    out = _workdir(Path(args.repo)) / "scout.json"
    out.write_text(res.value.model_dump_json(indent=1), encoding="utf-8")
    for c in res.value.capabilities:
        print(f"* {c.name}: {c.title}\n    {c.description}\n    entry: {', '.join(c.entry_points)}")
    if res.resolved:
        print(f"\nresolved model references: {len(res.resolved)}")
    if res.dropped:
        print(f"rejected references: {res.dropped}")
    print(f"\nwrote {out}")


def cmd_compile(args) -> None:
    a = analyze(args.repo)
    p = ModelProvider.from_env(args.env)
    scout_file = _workdir(Path(args.repo)) / "scout.json"
    if scout_file.exists() and not args.rescout:
        candidates = ScoutResult.model_validate_json(scout_file.read_text(encoding="utf-8")).capabilities
    else:
        res = scout(p, a)
        scout_file.write_text(res.value.model_dump_json(indent=1), encoding="utf-8")
        candidates = res.value.capabilities
    from zyven.catalog.catalog import Catalog  # reviewer-curated entries apply to catalog repos
    cat_file = Path("catalog/repos.json")
    if cat_file.exists():
        cat = Catalog(cat_file, Path("workspace"))
        for r in cat.repos:
            if cat.checkout_dir(r).resolve() == Path(args.repo).resolve():
                candidates = cat.capabilities(r)
    cand = next((c for c in candidates if c.name == args.capability), None) or \
        next((c for c in candidates if args.capability in c.name), None)
    if args.entry:
        # Human-edited boundary: the reviewer names the entry points (resolved like model references).
        from zyven.ai.schemas import CandidateCapability
        from zyven.analysis.refs import RefResolver
        ok, bad = RefResolver(a).resolve_all(args.entry)
        if bad:
            sys.exit(f"unknown entry points: {bad}")
        base = cand or CandidateCapability(name=args.capability, title=args.capability.replace("_", " ").title(),
                                           description=args.description or args.capability.replace("_", " "),
                                           entry_points=[], why_agents_need_it="selected by a human reviewer")
        cand = base.model_copy(update={"name": args.capability, "entry_points": ok,
                                       "description": args.description or base.description})
        print(f"boundary set by reviewer: {', '.join(ok)}")
    if cand is None:
        sys.exit(f"capability {args.capability!r} not found; available: {', '.join(c.name for c in candidates)}")
    r = compile_capability(p, a, candidate=cand, skills_root=Path(args.out), max_repairs=args.max_repairs)
    checks = f" ({', '.join(r.report.to_dict()['verified_for'])})" if r.report else ""
    print(f"\nskill: {r.skill_dir}\nverified: {r.verified}{checks}")
    sys.exit(0 if r.verified else 1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="zyven")
    ap.add_argument("--env", default=".env")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("analyze"); s.add_argument("repo"); s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("scout"); s.add_argument("repo"); s.set_defaults(fn=cmd_scout)
    s = sub.add_parser("compile"); s.add_argument("repo"); s.add_argument("--capability", required=True)
    s.add_argument("--out", default="skills"); s.add_argument("--max-repairs", type=int, default=2)
    s.add_argument("--rescout", action="store_true")
    s.add_argument("--entry", action="append", help="override entry points (human-edited boundary); repeatable")
    s.add_argument("--description", help="capability description when defining it with --entry")
    s.set_defaults(fn=cmd_compile)
    s = sub.add_parser("board"); s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=lambda a: __import__("zyven.orchestrator.server", fromlist=["serve"]).serve(port=a.port))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args.fn(args)


if __name__ == "__main__":
    main()
