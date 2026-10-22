"""Before/after evaluation: the same model on the same Nepali tasks, without vs. with a skill.

Usage:
  uv run python eval/run_eval.py                       # both conditions, manual skill
  uv run python eval/run_eval.py --limit 4             # quick smoke run
  uv run python eval/run_eval.py --skill path/to/server.py --label compiled
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.interpreter import PythonToolBox, docker_ready, resolve_libraries  # noqa: E402
from eval.tasks import Task, generate  # noqa: E402
from zyven.agent.loop import run_agent  # noqa: E402
from zyven.agent.mcp_tools import MCPServerSpec, ToolBox  # noqa: E402
from zyven.ai.provider import ModelProvider  # noqa: E402
from zyven.memory.skills import skill_server_spec  # noqa: E402

SYSTEM = (
    "You are a helpful assistant. Answer the user's question. "
    "Finish your reply with one final line in exactly this form:\n"
    "ANSWER: <value>\n"
    "Use YYYY-MM-DD for dates, the English weekday name for weekdays (e.g. Monday), "
    "and the operator's name for phone operators. Always give your best single answer."
)

MAX_TOKENS = 4096  # same output budget per model call in every condition

_DATE_RE = re.compile(r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})")
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_BS_MONTHS = {
    1: ["baisakh", "baishakh", "vaisakh", "vaishakh", "baisak"], 2: ["jestha", "jeth", "jyestha"],
    3: ["asar", "ashadh", "asadh", "ashar", "asaar"], 4: ["shrawan", "saun", "sawan", "srawan", "shravan"],
    5: ["bhadra", "bhadau", "bhadra"], 6: ["ashwin", "asoj", "ashoj", "aswin", "asauj"],
    7: ["kartik", "kattik"], 8: ["mangsir", "marga", "mansir", "mangshir"],
    9: ["poush", "push", "paush", "pus", "pous"], 10: ["magh"], 11: ["falgun", "phalgun", "fagun", "phagun"],
    12: ["chaitra", "chait", "chaitr"],
}
_AD_MONTHS = {m: [n] for m, n in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_OPERATOR_ALIASES = {
    "Nepal Telecom": ["nepaltelecom", "ntc", "namaste"],
    "Ncell": ["ncell"],
    "Smart Cell": ["smartcell", "smart"],
}


def extract_answer(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip().upper().startswith("ANSWER")]
    raw = lines[-1].split(":", 1)[-1] if lines else text
    return raw.strip().strip("*").strip()


def parse_date(answer: str, months: dict[int, list[str]]) -> str | None:
    """Accept YYYY-MM-DD or a written form such as 'Jestha 29, 2057' / 'November 18, 1991'."""
    a = answer.translate(_DEVANAGARI_DIGITS)
    m = _DATE_RE.search(a)
    if m:
        return "{:04d}-{:02d}-{:02d}".format(*map(int, m.groups()))
    low = a.lower()
    month = next((num for num, names in months.items() if any(re.search(rf"\b{n}", low) for n in names)), None)
    year = re.search(r"\b(\d{4})\b", low)
    day = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", re.sub(r"\b\d{4}\b", " ", low))
    if month and year and day:
        return f"{int(year.group(1)):04d}-{month:02d}-{int(day.group(1)):02d}"
    return None


SUITE: dict = {}  # filled below / in main(): system prompt, scorer, task generator for the chosen suite


def score(task: Task, answer: str) -> bool:
    a = answer.translate(_DEVANAGARI_DIGITS)
    if task.category in ("ad_to_bs", "bs_to_ad"):
        months = _BS_MONTHS if task.category == "ad_to_bs" else _AD_MONTHS
        return parse_date(a, months) == task.expected
    if task.category == "bs_weekday":
        return task.expected.lower() in a.lower()
    if task.category == "phone_operator":
        norm = re.sub(r"[^a-z]", "", a.lower())
        hits = [op for op, aliases in _OPERATOR_ALIASES.items() if any(x in norm for x in aliases)]
        return hits == [task.expected]
    raise ValueError(task.category)


async def run_condition(provider, tasks, label, toolbox, concurrency, out, system=None, run=1, seed=None):
    sem = asyncio.Semaphore(concurrency)
    records = []

    async def one(task: Task):
        async with sem:
            r = await run_agent(provider, task.question, toolbox, system=system or SUITE["system"],
                                max_tokens=MAX_TOKENS, seed=seed)
            ans = extract_answer(r.final_text)
            rec = {
                "condition": label, "run": run, "model": provider.model, "host": provider.host, "seed": seed,
                "served_by": sorted(r.served_by),
                "task_id": task.id, "category": task.category,
                "question": task.question, "expected": task.expected, "answer": ans,
                "correct": (not r.error) and SUITE["score"](task, ans), "error": r.error,
                "truncated": r.truncated, "recovered": r.recovered,
                "tool_calls": [asdict(c) for c in r.tool_calls], "steps": r.steps,
                "seconds": round(r.seconds, 2),
                "tokens_in": r.prompt_tokens, "tokens_out": r.completion_tokens,
                "final_text": r.final_text,
            }
            records.append(rec)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            mark = "✓" if rec["correct"] else ("!" if r.error else ("…" if r.truncated else "✗"))
            print(f"  [{label} run {run}] {mark} {task.id:18} expected={task.expected:14} got={ans[:40]!r}",
                  flush=True)

    await asyncio.gather(*(one(t) for t in tasks))
    errored = {r["task_id"] for r in records if r["error"]}
    if errored:
        print(f"  [{label} run {run}] retrying {len(errored)} task(s) that hit API errors")
        records[:] = [r for r in records if r["task_id"] not in errored]
        await asyncio.gather(*(one(t) for t in tasks if t.id in errored))
    return records


def _mean_half_range(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    half = (max(values) - min(values)) / 2 if len(values) > 1 else 0.0
    return mean, half


def _fmt_pct(mean: float, half: float, runs: int) -> str:
    return f"{mean:.0f}%" if runs == 1 else f"{mean:.0f}% ± {half:.0f}%"


def _fmt_num(mean: float, half: float, runs: int, digits: int = 0) -> str:
    fmt = f"{{:.{digits}f}}"
    return fmt.format(mean) if runs == 1 else f"{fmt.format(mean)} ± {fmt.format(half)}"


def summarize(records):
    by = {}
    for cond in dict.fromkeys(r["condition"] for r in records):
        cond_recs = [r for r in records if r["condition"] == cond]
        runs = sorted({r.get("run", 1) for r in cond_recs})
        cells = {}
        for cat in dict.fromkeys(r["category"] for r in cond_recs):
            pcts = []
            for run in runs:
                rs = [r for r in cond_recs
                      if r.get("run", 1) == run and r["category"] == cat and not r["error"]]
                if rs:
                    pcts.append(100 * sum(1 for r in rs if r["correct"]) / len(rs))
            cells[cat] = _mean_half_range(pcts)

        totals = []
        for run in runs:
            rs = [r for r in cond_recs if r.get("run", 1) == run and not r["error"]]
            if rs:
                totals.append(100 * sum(1 for r in rs if r["correct"]) / len(rs))

        secs, toks, errs, trunc, recov = [], [], [], [], []
        for run in runs:
            rs = [r for r in cond_recs if r.get("run", 1) == run]
            if not rs:
                continue
            secs.append(sum(r["seconds"] for r in rs) / len(rs))
            toks.append(sum(r.get("tokens_in", 0) + r.get("tokens_out", 0) for r in rs) / len(rs))
            errs.append(sum(1 for r in rs if r["error"]))
            trunc.append(sum(1 for r in rs if r.get("truncated")))
            recov.append(sum(1 for r in rs if r.get("recovered")))

        by[cond] = {
            "runs": len(runs), "cells": cells, "total": _mean_half_range(totals),
            "secs": _mean_half_range(secs), "tokens": _mean_half_range(toks),
            "errors": _mean_half_range(errs), "trunc": _mean_half_range(trunc),
            "recovered": _mean_half_range(recov),
        }
    return by


def _skill_spec(name: str, script: Path):
    """Compiled skills (a provenance.json next to server.py) run sandboxed, as they do for the agent; the
    hand-written reference skill in toolkit/ is our own code and runs on the host."""
    prov = script.parent / "provenance.json"
    if prov.exists():
        return skill_server_spec(name, script.parent, json.loads(prov.read_text(encoding="utf-8")).get("source_checkout"))
    return MCPServerSpec.python_script(name, script)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", action="append", help="MCP server script; repeat for several skills")
    ap.add_argument("--label", default="manual")
    ap.add_argument("--limit", type=int, default=10, help="tasks per category")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--suite", choices=["nepali", "stdnum", "global"], default="nepali")
    ap.add_argument("--interpreter", action="store_true",
                    help="also run interpreter with and without the suite's library")
    ap.add_argument("--library", action="append",
                    help="importable package for interpreter_lib; repeatable (default: suite library)")
    ap.add_argument("--repeat", type=int, default=1, help="runs per condition (default: 1)")
    ap.add_argument("--seed", type=int, default=None,
                    help="model seed for the first repeat; incremented for each repeat")
    ap.add_argument("--task-seed", type=int, default=None, help="override the suite's task seed")
    args = ap.parse_args()
    if args.repeat < 1:
        ap.error("--repeat must be at least 1")
    if args.library and not args.interpreter:
        ap.error("--library requires --interpreter")

    provider = ModelProvider.from_env(ROOT / ".env")
    if args.suite == "global":
        from eval import tasks_global
        SUITE.update(system=SYSTEM_BASE + " " + tasks_global.SYSTEM_HINT, score=tasks_global.score,
                     generate=tasks_global.generate, libraries=["hijridate", "pyluach", "phonenumbers"],
                     task_seed=1447)
    if args.suite == "stdnum":
        from eval import tasks_stdnum
        SUITE.update(system=SYSTEM_BASE + " " + tasks_stdnum.SYSTEM_HINT, score=tasks_stdnum.score,
                     generate=tasks_stdnum.generate, libraries=["stdnum"], task_seed=97)

    task_seed = args.task_seed if args.task_seed is not None else SUITE["task_seed"]
    tasks = SUITE["generate"](per_category=args.limit, seed=task_seed)
    results_dir = ROOT / "eval/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = results_dir / f"run-{stamp}.jsonl"

    conditions: list[tuple[str, object, str | None]] = []
    if not args.skip_baseline:
        conditions.append(("no_tools", None, None))
    if args.interpreter:
        if not docker_ready():
            ap.error("Docker is not running or zyven-sandbox:py312 is missing. Start Docker, then run: "
                     "docker build -t zyven-sandbox:py312 zyven/sandbox")
        names = args.library or SUITE["libraries"]
        try:
            lib_paths = resolve_libraries(names)
        except RuntimeError as e:
            ap.error(str(e))
        lib_hint = (" You may use the run_python tool to execute Python 3.12 in a network-isolated sandbox. "
                    f"These packages are importable: {', '.join(names)}.")
        plain_hint = (" You may use the run_python tool to execute Python 3.12 in a network-isolated sandbox. "
                      "Only the Python standard library and packages baked into the sandbox image are available; "
                      "the suite libraries are not installed and packages cannot be installed.")
        conditions.append(("interpreter_lib", PythonToolBox(lib_paths, names), SUITE["system"] + lib_hint))
        conditions.append(("interpreter_no_lib", PythonToolBox(), SUITE["system"] + plain_hint))

    skill_label = f"with_{args.label}"
    metadata = {
        "suite": args.suite, "model": provider.model, "host": provider.host, "label": args.label,
        "tasks_per_category": args.limit, "task_seed": task_seed, "seed": args.seed,
        "run_seeds": [args.seed + i - 1 if args.seed is not None else None
                      for i in range(1, args.repeat + 1)],
        "runs": args.repeat, "conditions": [c[0] for c in conditions] + [skill_label],
        "max_tokens": MAX_TOKENS, "created": stamp,
    }
    metadata_path = results_dir / f"run-{stamp}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    records = []
    with path.open("w", encoding="utf-8") as out:
        for run in range(1, args.repeat + 1):
            run_seed = args.seed + run - 1 if args.seed is not None else None
            for label, toolbox, system in conditions:
                suffix = " alone" if label == "no_tools" else ""
                print(f"Condition {label}: {provider.model}{suffix} ({len(tasks)} tasks, run {run}/{args.repeat})")
                records += await run_condition(provider, tasks, label, toolbox, args.concurrency, out,
                                               system=system, run=run, seed=run_seed)

        async with ToolBox() as tb:
            names = []
            for i, script in enumerate(args.skill or [str(ROOT / "toolkit/py_nepali_manual/server.py")]):
                names += await tb.add_server(_skill_spec(f"{args.label}-{i}", Path(script)))
            print(f"  tools: {names}")
            for run in range(1, args.repeat + 1):
                run_seed = args.seed + run - 1 if args.seed is not None else None
                print(f"Condition {skill_label}: {provider.model} ({len(tasks)} tasks, run {run}/{args.repeat})")
                records += await run_condition(provider, tasks, skill_label, tb, args.concurrency, out,
                                               run=run, seed=run_seed)

    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    metadata["served_by"] = sorted({h for r in records for h in r.get("served_by", [])})
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    by = summarize(records)
    cats = list(dict.fromkeys(t.category for t in tasks))
    lines = [
        f"# Eval run {stamp}", "",
        f"Suite: {args.suite} · model: `{provider.model}` · host: `{provider.host}` · "
        f"tasks/category: {args.limit} · task seed: {task_seed} · runs: {args.repeat}", "",
        "Cells are mean accuracy (correct/answered) ± half-range across runs. "
        "API errors (after retries) are excluded from accuracy and listed separately; "
        "Avg sec/task and Tokens/task include those attempts.", "",
        f"Output budget: {MAX_TOKENS} tokens per model call in every condition. "
        "'Hit cap' = the model ran out of budget before answering (scored wrong).", "",
        "'Answer-now retries' = budget exhausted once, model asked to answer directly "
        "(same rule in all conditions).", "",
        "| Condition | " + " | ".join(cats) +
        " | Total | Runs | Answer-now retries | Hit cap | API errors | Avg sec/task | Tokens/task |",
        "|---" * (len(cats) + 8) + "|",
    ]
    for cond, s in by.items():
        runs = s["runs"]
        row = []
        for c in cats:
            mean, half = s["cells"][c]
            row.append(_fmt_pct(mean, half, runs))
        total = _fmt_pct(s["total"][0], s["total"][1], runs)
        recov = _fmt_num(s["recovered"][0], s["recovered"][1], runs)
        trunc = _fmt_num(s["trunc"][0], s["trunc"][1], runs)
        errs = _fmt_num(s["errors"][0], s["errors"][1], runs)
        secs = _fmt_num(s["secs"][0], s["secs"][1], runs, 1)
        toks = _fmt_num(s["tokens"][0], s["tokens"][1], runs)
        lines.append(f"| {cond} | " + " | ".join(row) +
                     f" | **{total}** | {runs} | {recov} | {trunc} | {errs} | {secs} | {toks} |")
    stats = provider.stats
    lines += ["", f"Model calls: {stats.calls} · retries after API errors: {stats.retries} · "
              f"hard failures: {stats.failures} · tokens in/out: {stats.prompt_tokens}/{stats.completion_tokens} · "
              f"failovers to backup host: {stats.failovers}",
              "", f"Raw records: `{path.name}` · Metadata: `{metadata_path.name}`"]
    report = "\n".join(lines)
    (results_dir / f"run-{stamp}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


SYSTEM_BASE = (
    "You are a helpful assistant. Answer the user's question. "
    "Finish your reply with one final line in exactly this form:\nANSWER: <value>\n"
    "Always give your best single answer."
)
SUITE.update(system=SYSTEM, score=score, generate=generate, libraries=["nepali"], task_seed=2082)


if __name__ == "__main__":
    asyncio.run(main())
