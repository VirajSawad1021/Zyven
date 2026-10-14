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
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.tasks import Task, generate  # noqa: E402
from zyven.agent.loop import run_agent  # noqa: E402
from zyven.agent.mcp_tools import MCPServerSpec, ToolBox  # noqa: E402
from zyven.ai.provider import ModelProvider  # noqa: E402

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


async def run_condition(provider, tasks, label, toolbox, concurrency, out):
    sem = asyncio.Semaphore(concurrency)
    records = []

    async def one(task: Task):
        async with sem:
            r = await run_agent(provider, task.question, toolbox, system=SUITE["system"], max_tokens=MAX_TOKENS)
            ans = extract_answer(r.final_text)
            rec = {
                "condition": label, "task_id": task.id, "category": task.category,
                "question": task.question, "expected": task.expected, "answer": ans,
                "correct": (not r.error) and SUITE["score"](task, ans), "error": r.error,
                "truncated": r.truncated, "recovered": r.recovered,
                "tool_calls": [asdict(c) for c in r.tool_calls], "steps": r.steps,
                "seconds": round(r.seconds, 2), "final_text": r.final_text,
            }
            records.append(rec)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            mark = "✓" if rec["correct"] else ("!" if r.error else ("…" if r.truncated else "✗"))
            print(f"  [{label}] {mark} {task.id:18} expected={task.expected:14} got={ans[:40]!r}", flush=True)

    await asyncio.gather(*(one(t) for t in tasks))
    errored = {r["task_id"] for r in records if r["error"]}
    if errored:
        print(f"  [{label}] retrying {len(errored)} task(s) that hit API errors")
        records[:] = [r for r in records if r["task_id"] not in errored]
        await asyncio.gather(*(one(t) for t in tasks if t.id in errored))
    return records


def summarize(records):
    by = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in records:
        if r["error"]:
            continue  # API failures are reported separately, not scored as wrong
        cell = by[r["condition"]][r["category"]]
        cell[0] += r["correct"]
        cell[1] += 1
    return by


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", action="append", help="MCP server script; repeat for several skills")
    ap.add_argument("--label", default="manual")
    ap.add_argument("--limit", type=int, default=10, help="tasks per category")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--suite", choices=["nepali", "stdnum"], default="nepali")
    args = ap.parse_args()

    provider = ModelProvider.from_env(ROOT / ".env")
    if args.suite == "stdnum":
        from eval import tasks_stdnum
        SUITE.update(system=SYSTEM_BASE + " " + tasks_stdnum.SYSTEM_HINT, score=tasks_stdnum.score,
                     generate=tasks_stdnum.generate)
    tasks = SUITE["generate"](per_category=args.limit)
    results_dir = ROOT / "eval/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = results_dir / f"run-{stamp}.jsonl"

    records = []
    with path.open("w", encoding="utf-8") as out:
        if not args.skip_baseline:
            print(f"Condition A: {provider.model} alone ({len(tasks)} tasks)")
            records += await run_condition(provider, tasks, "no_tools", None, args.concurrency, out)
        print(f"Condition B: {provider.model} + skill '{args.label}'")
        async with ToolBox() as tb:
            names = []
            for i, script in enumerate(args.skill or [str(ROOT / "toolkit/py_nepali_manual/server.py")]):
                names += await tb.add_server(MCPServerSpec.python_script(f"{args.label}-{i}", script))
            print(f"  tools: {names}")
            records += await run_condition(provider, tasks, f"with_{args.label}", tb, args.concurrency, out)

    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    by = summarize(records)
    cats = list(dict.fromkeys(t.category for t in tasks))
    lines = [f"# Eval run {stamp}", "", f"Suite: {args.suite} · model: `{provider.label}` · tasks/category: {args.limit}", "",
             "Cells are correct / answered. API errors (after retries) are excluded and listed separately.", "",
             f"Output budget: {MAX_TOKENS} tokens per model call in every condition. "
             "'Hit cap' = the model ran out of budget before answering (scored wrong).", "",
             "'Answer-now retries' = budget exhausted once, model asked to answer directly (same rule in all conditions).", "",
             "| Condition | " + " | ".join(cats) + " | Total | Answer-now retries | Hit cap | API errors | Avg sec/task |",
             "|---" * (len(cats) + 6) + "|"]
    for cond, cells in by.items():
        tot_c = sum(c[0] for c in cells.values())
        tot_n = sum(c[1] for c in cells.values())
        row = [f"{cells[c][0]}/{cells[c][1]}" for c in cats]
        cond_recs = [r for r in records if r["condition"] == cond]
        errs = sum(1 for r in cond_recs if r["error"])
        trunc = sum(1 for r in cond_recs if r.get("truncated"))
        recov = sum(1 for r in cond_recs if r.get("recovered"))
        avg = sum(r["seconds"] for r in cond_recs) / max(len(cond_recs), 1)
        pct = 100 * tot_c / tot_n if tot_n else 0
        lines.append(f"| {cond} | " + " | ".join(row) + f" | **{tot_c}/{tot_n} ({pct:.0f}%)** | {recov} | {trunc} | {errs} | {avg:.1f} |")
    s = provider.stats
    lines += ["", f"Model calls: {s.calls} · retries after API errors: {s.retries} · hard failures: {s.failures} · "
              f"tokens in/out: {s.prompt_tokens}/{s.completion_tokens} · failovers to backup host: {s.failovers}", "", f"Raw records: `{path.name}`"]
    report = "\n".join(lines)
    (results_dir / f"run-{stamp}.md").write_text(report, encoding="utf-8")
    print("\n" + report)


SYSTEM_BASE = (
    "You are a helpful assistant. Answer the user's question. "
    "Finish your reply with one final line in exactly this form:\nANSWER: <value>\n"
    "Always give your best single answer."
)
SUITE.update(system=SYSTEM, score=score, generate=generate)


if __name__ == "__main__":
    asyncio.run(main())
