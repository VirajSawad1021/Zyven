"""Agent showdown: compile the same capability with several models or coding agents, and compare what the gates say.

    uv run python eval/showdown.py workspace/repos/packaging --capability version_specifiers \\
        --agents model,codex,qoder --mutants 6

For each contender, `zyven compile --agent <name>` runs with every role played by that contender. The table compares:
  * verified or not, compile attempts, wall time, tools kept and dropped
  * the mutation score of the skill it produced (eval/mutation_test.py --calibrate): how many deliberately broken
    copies of its own tool bodies its own differential cases catch, i.e. the quality of the tests it wrote
  * how many of its Tester cases had to be calibrated away (wrong expected values)

The same pinned commit, analysis, catalog entry and gates are used for everyone. Compiled skills stay in a scratch
folder and are never committed: closed models and coding agents are labelled in their provenance, and the repository
keeps published results open-weight (scripts/check_open_models.py). The summary goes to eval/showdown/, not
eval/results/. One run per contender is one sample, not a benchmark: model output varies from run to run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compile_with(agent: str, repo: Path, capability: str, out: Path, timeout: float) -> dict:
    started = time.monotonic()
    cmd = [sys.executable, "-m", "zyven.cli", "compile", str(repo), "--capability", capability, "--out", str(out)]
    if agent != "model":
        cmd += ["--agent", agent]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                           env=env, timeout=timeout)
        log = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        log = f"TIMEOUT after {timeout:.0f}s\n{(e.stdout or '')[-2000:] if isinstance(e.stdout, str) else ''}"
    seconds = round(time.monotonic() - started)
    skill = out / capability
    row = {"contender": agent, "seconds": seconds, "verified": False, "attempts": None, "tools": 0, "dropped": [],
           "who": "", "gates": {}, "cases": 0,  # no local paths in what gets committed
           "log_tail": "\n".join(ln for ln in log.strip().splitlines()[-6:] if not ln.startswith("skill:"))}
    if (skill / "provenance.json").exists():
        prov = json.loads((skill / "provenance.json").read_text(encoding="utf-8"))
        row.update(attempts=prov.get("attempts"), dropped=sorted(prov.get("dropped_tools") or {}),
                   who=prov.get("model", ""))
    if (skill / "validation-report.json").exists():
        rep = json.loads((skill / "validation-report.json").read_text(encoding="utf-8"))
        row["verified"] = bool(rep.get("passed"))
        row["gates"] = {g["name"]: g["passed"] for g in rep.get("gates", [])}
    if (skill / "capability.json").exists():
        row["tools"] = len(json.loads((skill / "capability.json").read_text(encoding="utf-8")).get("tools", []))
    if (skill / "diff_tests.json").exists():
        row["cases"] = len(json.loads((skill / "diff_tests.json").read_text(encoding="utf-8")).get("cases", []))
    row["skill_dir"] = str(skill)
    return row


def mutation_score(skill: Path, mutants: int, seed: int, out: Path) -> dict:
    cmd = [sys.executable, str(ROOT / "eval" / "mutation_test.py"), str(skill), "--max", str(mutants), "--seed",
           str(seed), "--calibrate", "--out", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    reports = sorted(out.glob("mutation-*.json"))
    if p.returncode != 0 or not reports:
        return {"error": (p.stdout + p.stderr).strip().splitlines()[-1][:300] if (p.stdout + p.stderr).strip() else "failed"}
    data = json.loads(reports[-1].read_text(encoding="utf-8"))
    return {"killed": data["killed"], "mutants": data["mutants"], "calibrated": len(data.get("calibrated", [])),
            "survivors": [f"{r['tool']} {r['operator']} ({r['where']})" for r in data["results"] if not r["killed_by"]
                          and not r["detail"].startswith("ERROR")]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--capability", required=True)
    ap.add_argument("--agents", default="model,codex", help="comma list: model (the chat model in .env), codex, "
                                                             "claude, agy, opencode, qoder (optionally name:model)")
    ap.add_argument("--mutants", type=int, default=6, help="mutants per tool for the test-quality score (0 = skip)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--work", type=Path, default=None, help="scratch folder for the compiled skills (not committed)")
    args = ap.parse_args()
    work = args.work or Path(tempfile.mkdtemp(prefix="zyven-showdown-"))
    rows = []
    for agent in [a.strip() for a in args.agents.split(",") if a.strip()]:
        print(f"== {agent}: compiling {args.capability} ...", flush=True)
        row = compile_with(agent, args.repo, args.capability, work / agent.replace(":", "_"), args.timeout)
        print(f"   verified={row['verified']} attempts={row['attempts']} {row['seconds']}s tools={row['tools']} "
              f"dropped={row['dropped']} cases={row['cases']}", flush=True)
        if row["verified"] and args.mutants:
            row["mutation"] = mutation_score(Path(row["skill_dir"]), args.mutants, args.seed,
                                             work / f"mut-{agent.replace(':', '_')}")
            print(f"   mutation: {row['mutation']}", flush=True)
        rows.append(row)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "eval" / "showdown"
    out.mkdir(parents=True, exist_ok=True)
    md = [f"# Agent showdown: `{args.capability}` ({time.strftime('%Y-%m-%d')})", "",
          f"Repository `{args.repo.name}` at its pinned commit; every role played by the contender; same gates. "
          "One run each: a sample, not a benchmark. Compiled skills were not committed.", "",
          "| Contender | Verified | Attempts | Time | Tools kept | Dropped | Tester cases | Mutants caught | Cases calibrated |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r.get("mutation") or {}
        caught = (f"{m['killed']}/{m['mutants']}" if "killed" in m else (m.get("error", "-")[:40] if m else "-"))
        md.append(f"| {r['contender']} ({r['who'] or 'see log'}) | {'yes' if r['verified'] else 'no'} | "
                  f"{r['attempts'] if r['attempts'] is not None else '-'} | {r['seconds']} s | {r['tools']} | "
                  f"{', '.join(r['dropped']) or '-'} | {r['cases']} | {caught} | {m.get('calibrated', '-')} |")
    for r in rows:
        surv = (r.get("mutation") or {}).get("survivors")
        if surv:
            md += ["", f"Survivors for {r['contender']}: " + "; ".join(surv)]
        if not r["verified"]:
            md += ["", f"{r['contender']} did not verify. Last log lines:", "```", r["log_tail"], "```"]
    (out / f"showdown-{args.capability}-{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / f"showdown-{args.capability}-{stamp}.json").write_text(
        json.dumps({k: v for k, v in vars(args).items() if k not in ("work", "repo")} | {"repo": args.repo.name} |
                   {"rows": [{k: v for k, v in r.items() if k != "skill_dir"} for r in rows]}, indent=1, default=str),
        encoding="utf-8")
    print("\n" + "\n".join(md))


if __name__ == "__main__":
    main()
