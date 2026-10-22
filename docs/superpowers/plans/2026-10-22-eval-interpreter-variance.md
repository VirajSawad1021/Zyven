# Eval Interpreter Baseline and Run Variance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sandboxed `run_python` interpreter baseline and repeated-run metadata/summaries to the evaluation harness.

**Architecture:** A duck-typed `PythonToolBox` implements the same `openai_tools`/`call` surface as `ToolBox`, so `run_agent` needs no new tool abstraction. `run_eval.py` runs the new conditions and aggregates per-run results into mean ± half-range. Provider and agent result objects carry token counts and accept an optional model seed.

**Tech Stack:** Python 3.11+, asyncio, httpx, Docker sandbox runner, pytest.

---

### Task 1: Expose seed and token usage on provider calls

**Files:**
- Modify: `zyven/ai/provider.py:68-76`, `zyven/ai/provider.py:154-233`
- Test: `tests/test_foundation.py:72-90`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_foundation.py` after `test_retries_server_errors_then_succeeds`:

```python
def test_seed_and_token_usage_are_exposed():
    seen: list = []
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    p._client = fake_host([(200, reply("ok"))], seen)
    r = p.chat([{"role": "user", "content": "hi"}], seed=123)
    assert seen[0]["seed"] == 123
    assert (r.prompt_tokens, r.completion_tokens) == (3, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_foundation.py::test_seed_and_token_usage_are_exposed -q`

Expected: FAIL because `chat()` does not accept `seed`.

- [ ] **Step 3: Implement the provider changes**

In `zyven/ai/provider.py`, add fields to `ChatResult`:

```python
    served_by: str = ""  # host/model that produced this reply (primary or fallback)
    prompt_tokens: int = 0
    completion_tokens: int = 0
```

Change `chat()` and the fallback argument tuple:

```python
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        """Primary host first; on failure (or while it is cooling down) the fallback host serves."""
        args = (messages, tools, response_format, temperature, max_tokens, seed)
```

Add the seed parameter to `_chat_host()` and its request body:

```python
    def _chat_host(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._for_host(messages),
            "temperature": self.temperature if temperature is None else temperature,
        }
        if seed is not None:
            body["seed"] = seed
```

Replace the usage block and return value with:

```python
                    usage = data.get("usage") or {}
                    prompt_tokens = usage.get("prompt_tokens", 0) or 0
                    completion_tokens = usage.get("completion_tokens", 0) or 0
                    log.info("model call ok in %.1fs (attempt %d, finish=%s, out_tokens=%s)", latency, attempt,
                             choice.get("finish_reason"), completion_tokens)
                    self.stats.calls += 1
                    self.stats.retries += attempt - 1
                    self.stats.latency_s += latency
                    self.stats.prompt_tokens += prompt_tokens
                    self.stats.completion_tokens += completion_tokens
                    return ChatResult(
                        content=strip_thoughts(msg.get("content")),
                        tool_calls=msg.get("tool_calls") or [],
                        raw_message=msg,
                        latency_s=latency,
                        attempts=attempt,
                        finish_reason=choice.get("finish_reason"),
                        served_by=f"{self.model}@{self.host}",
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
```

- [ ] **Step 4: Run the provider tests**

Run: `uv run pytest tests/test_foundation.py -q`

Expected: PASS (including the new test).

- [ ] **Step 5: Commit**

```bash
git add zyven/ai/provider.py tests/test_foundation.py
git commit -m "Provider: expose seed and token usage"
```

---

### Task 2: Accumulate tokens and pass seed through the agent loop

**Files:**
- Modify: `zyven/agent/loop.py:23-54`
- Test: `tests/test_foundation.py` (new test)

- [ ] **Step 1: Write the failing test**

Add imports near the top of `tests/test_foundation.py`:

```python
import asyncio
```

Add `run_agent` to the imports:

```python
from zyven.agent.loop import run_agent  # noqa: E402
```

Add this test after the provider test from Task 1:

```python
def test_agent_accumulates_token_usage():
    p = make([(200, reply("ANSWER: 42"))])
    r = asyncio.run(run_agent(p, "q"))
    assert (r.prompt_tokens, r.completion_tokens) == (3, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_foundation.py::test_agent_accumulates_token_usage -q`

Expected: FAIL because `AgentResult` has no `prompt_tokens`.

- [ ] **Step 3: Implement the agent changes**

In `zyven/agent/loop.py`, add token fields to `AgentResult`:

```python
    truncated: bool = False  # model hit the output cap before answering
    recovered: bool = False  # a budget-exhausted reply triggered the one-time "answer now" retry
    prompt_tokens: int = 0
    completion_tokens: int = 0
```

Add `seed` to `run_agent()` and pass it to every model call:

```python
async def run_agent(
    provider: ModelProvider,
    task: str,
    toolbox: ToolBox | None = None,
    system: str | None = None,
    max_steps: int = 6,
    max_tokens: int | None = None,
    seed: int | None = None,
) -> AgentResult:
```

```python
            reply = await asyncio.to_thread(provider.chat, messages, tools, None, None, max_tokens, seed)
```

Immediately after the `provider.chat` call succeeds, accumulate usage:

```python
        result.prompt_tokens += reply.prompt_tokens
        result.completion_tokens += reply.completion_tokens
```

- [ ] **Step 4: Run the agent tests**

Run: `uv run pytest tests/test_foundation.py tests/test_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add zyven/agent/loop.py tests/test_foundation.py
git commit -m "Agent: track token usage and accept a model seed"
```

---

### Task 3: Add the sandboxed `run_python` tool

**Files:**
- Create: `eval/interpreter.py`
- Create: `tests/test_eval_harness.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_harness.py`:

```python
"""Offline tests for the eval interpreter tool and repeated-run summaries."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import interpreter  # noqa: E402
from eval.interpreter import PythonToolBox  # noqa: E402
from zyven.sandbox.runner import SandboxResult  # noqa: E402


def test_python_tool_runs_code_in_sandbox(monkeypatch):
    seen = {}

    def fake_run(command, mounts, policy, workdir):
        seen.update(command=command, mounts=mounts, policy=policy, workdir=workdir)
        return SandboxResult(command, 0, "42\n", "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print(42)"}))

    assert ok and out == "42"
    assert seen["command"] == ["python", "-c", "print(42)"]
    assert seen["policy"].network is False
    assert seen["policy"].timeout_s == 30
    assert seen["mounts"] == {}
    assert seen["workdir"] == "/tmp"


def test_python_tool_mounts_only_requested_library(monkeypatch, tmp_path):
    lib = tmp_path / "mylib"
    lib.mkdir()
    (lib / "__init__.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_run(command, mounts, policy, workdir):
        seen.update(mounts=mounts, policy=policy)
        return SandboxResult(command, 0, "", "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    tb = PythonToolBox([lib], ["mylib"])
    ok, _ = asyncio.run(tb.call("run_python", {"code": "import mylib"}))

    assert ok
    assert seen["mounts"] == {lib: "/libs/0/mylib"}
    assert seen["policy"].extra_env["PYTHONPATH"] == "/libs/0"
    assert "mylib" in tb.openai_tools[0]["function"]["description"]


def test_python_tool_rejects_bad_input():
    tb = PythonToolBox()
    assert asyncio.run(tb.call("other", {}))[0] is False
    ok, out = asyncio.run(tb.call("run_python", {"code": "  "}))
    assert not ok and "non-empty" in out


def test_python_tool_truncates_large_output(monkeypatch):
    def fake_run(command, mounts, policy, workdir):
        return SandboxResult(command, 0, "x" * 7000, "", 0.1)

    monkeypatch.setattr(interpreter.runner, "run", fake_run)
    ok, out = asyncio.run(PythonToolBox().call("run_python", {"code": "print('x')"}))

    assert ok
    assert out.endswith("...[truncated]")
    assert len(out) < 7000
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_harness.py -q`

Expected: FAIL because `eval/interpreter.py` does not exist.

- [ ] **Step 3: Create `eval/interpreter.py`**

```python
"""One sandboxed `run_python` tool for the evaluation interpreter conditions."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import Any

from zyven.sandbox import runner
from zyven.sandbox.runner import DEFAULT_IMAGE, SandboxPolicy

MAX_OUTPUT = 6000


def resolve_libraries(names: list[str]) -> list[Path]:
    """Resolve importable packages from the active environment to their package directories."""
    paths = []
    for name in names:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"cannot find importable package {name!r}")
        paths.append(Path(spec.origin).parent)
    return paths


def docker_ready(image: str = DEFAULT_IMAGE) -> bool:
    """True when the Docker daemon and the sandbox image are both available."""
    if not shutil.which("docker"):
        return False
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        if info.returncode != 0:
            return False
        img = subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=15)
        return img.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class PythonToolBox:
    """Duck-typed toolbox: only `openai_tools` and `async call(name, args)` are used by run_agent."""

    def __init__(self, libraries: list[Path] | None = None, library_names: list[str] | None = None,
                 timeout_s: int = 30) -> None:
        self.libraries = libraries or []
        self.library_names = library_names or []
        self.timeout_s = timeout_s
        self.openai_tools = [self._tool_spec()]

    def _tool_spec(self) -> dict[str, Any]:
        description = (
            "Execute Python 3.12 code in a network-isolated sandbox and return stdout/stderr. "
            "Use print() to inspect values. The working directory is read-only; use /tmp for temporary files."
        )
        if self.library_names:
            description += " These packages are importable: " + ", ".join(self.library_names) + "."
        else:
            description += " Only the Python standard library is available; packages cannot be installed."
        return {
            "type": "function",
            "function": {
                "name": "run_python",
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {"code": {"type": "string", "description": "Python source code to run."}},
                    "required": ["code"],
                },
            },
        }

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        if name != "run_python":
            return False, f"Unknown tool {name!r}. Available: run_python"
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return False, "run_python requires a non-empty string argument named 'code'."
        return await asyncio.to_thread(self._run, code)

    def _run(self, code: str) -> tuple[bool, str]:
        policy = SandboxPolicy(network=False, memory="512m", cpus="1", pids_limit=64, timeout_s=self.timeout_s)
        mounts: dict[Path, str] = {}
        search_paths = []
        for i, lib in enumerate(self.libraries):
            mounts[lib] = f"/libs/{i}/{lib.name}"
            search_paths.append(f"/libs/{i}")
        if search_paths:
            policy.extra_env["PYTHONPATH"] = ":".join(search_paths)

        result = runner.run(["python", "-c", code], mounts, policy, workdir="/tmp")
        text = ((result.stdout or "") + (result.stderr or "")).strip()
        if result.timed_out:
            text = f"timed out after {self.timeout_s}s\n{text}".strip()
        if not text:
            text = "(no output)"
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n...[truncated]"
        return result.ok, text
```

- [ ] **Step 4: Run the interpreter tests**

Run: `uv run pytest tests/test_eval_harness.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/interpreter.py tests/test_eval_harness.py
git commit -m "Eval: add sandboxed run_python tool"
```

---

### Task 4: Add conditions, repeats, and metadata to the runner

**Files:**
- Modify: `eval/run_eval.py:1-7`, `eval/run_eval.py:98-126`, `eval/run_eval.py:149-221`
- Test: `tests/test_eval_summary.py`

- [ ] **Step 1: Write the failing repeated-run summary tests**

Create `tests/test_eval_summary.py`:

```python
"""Offline tests for repeated-run summaries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_eval import _fmt_num, _fmt_pct, _mean_half_range, summarize  # noqa: E402


def test_mean_half_range_and_formatting():
    assert _mean_half_range([80, 100]) == (90.0, 10.0)
    assert _mean_half_range([90]) == (90.0, 0.0)
    assert _fmt_pct(90, 10, 2) == "90% ± 10%"
    assert _fmt_pct(90, 0, 1) == "90%"
    assert _fmt_num(12.34, 0.12, 2, 1) == "12.3 ± 0.1"


def _rec(cond, run, cat, correct, error=None, seconds=1.0, tokens_in=5, tokens_out=5):
    return {
        "condition": cond,
        "run": run,
        "category": cat,
        "correct": correct,
        "error": error,
        "seconds": seconds,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "truncated": False,
        "recovered": False,
    }


def test_summarize_reports_per_run_mean_and_half_range():
    records = [
        _rec("no_tools", 1, "x", True), _rec("no_tools", 1, "x", False),
        _rec("no_tools", 1, "y", True), _rec("no_tools", 1, "y", False),
        _rec("no_tools", 2, "x", True), _rec("no_tools", 2, "x", True),
        _rec("no_tools", 2, "y", True), _rec("no_tools", 2, "y", True),
    ]
    by = summarize(records)
    s = by["no_tools"]

    assert s["runs"] == 2
    assert s["cells"]["x"] == (75.0, 25.0)
    assert s["cells"]["y"] == (75.0, 25.0)
    assert s["total"] == (75.0, 25.0)
    assert s["tokens"] == (40.0, 0.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_eval_summary.py -q`

Expected: FAIL because `_mean_half_range` is not defined.

- [ ] **Step 3: Update `run_eval.py` imports and `run_condition()`**

Add the interpreter import:

```python
from eval.interpreter import PythonToolBox, docker_ready, resolve_libraries
```

Replace `run_condition()` with:

```python
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
```

- [ ] **Step 4: Add summary helpers and replace `summarize()`**

Replace the existing `summarize()` with:

```python
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
        cats = list(dict.fromkeys(r["category"] for r in cond_recs))
        cells = {}
        for cat in cats:
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
```

- [ ] **Step 5: Add CLI options and condition setup in `main()`**

Add arguments after `--suite`:

```python
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
```

Add suite defaults:

```python
    if args.suite == "global":
        from eval import tasks_global
        SUITE.update(system=SYSTEM_BASE + " " + tasks_global.SYSTEM_HINT, score=tasks_global.score,
                     generate=tasks_global.generate, libraries=["hijridate", "pyluach", "phonenumbers"],
                     task_seed=1447)
    if args.suite == "stdnum":
        from eval import tasks_stdnum
        SUITE.update(system=SYSTEM_BASE + " " + tasks_stdnum.SYSTEM_HINT, score=tasks_stdnum.score,
                     generate=tasks_stdnum.generate, libraries=["stdnum"], task_seed=97)
```

Replace the task generation and run block with:

```python
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
                      "Only the Python standard library is available; packages cannot be installed.")
        conditions.append(("interpreter_lib", PythonToolBox(lib_paths, names), SUITE["system"] + lib_hint))
        conditions.append(("interpreter_no_lib", PythonToolBox(), SUITE["system"] + plain_hint))

    records = []
    with path.open("w", encoding="utf-8") as out:
        for run in range(1, args.repeat + 1):
            run_seed = args.seed + run - 1 if args.seed is not None else None
            for label, toolbox, system in conditions:
                suffix = " alone" if label == "no_tools" else ""
                print(f"Condition {label}: {provider.model}{suffix} ({len(tasks)} tasks, run {run}/{args.repeat})")
                records += await run_condition(provider, tasks, label, toolbox, args.concurrency, out,
                                               system=system, run=run, seed=run_seed)

        skill_label = f"with_{args.label}"
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
```

- [ ] **Step 6: Add metadata sidecar and repeated-run report**

After the `with` block, add:

```python
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
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

    by = summarize(records)
    cats = list(dict.fromkeys(t.category for t in tasks))
    lines = [
        f"# Eval run {stamp}", "",
        f"Suite: {args.suite} · model: `{provider.model}` · host: `{provider.host}` · "
        f"tasks/category: {args.limit} · task seed: {task_seed} · runs: {args.repeat}", "",
        "Cells are mean accuracy (correct/answered) ± half-range across runs. "
        "API errors (after retries) are excluded and listed separately.", "",
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
        row = [_fmt_pct(*s["cells"][c], runs) for c in cats]
        total = _fmt_pct(*s["total"], runs)
        recov = _fmt_num(*s["recovered"], runs)
        trunc = _fmt_num(*s["trunc"], runs)
        errs = _fmt_num(*s["errors"], runs)
        secs = _fmt_num(*s["secs"], runs, 1)
        toks = _fmt_num(*s["tokens"], runs)
        lines.append(f"| {cond} | " + " | ".join(row) +
                     f" | **{total}** | {runs} | {recov} | {trunc} | {errs} | {secs} | {toks} |")
    s = provider.stats
    lines += ["", f"Model calls: {s.calls} · retries after API errors: {s.retries} · hard failures: {s.failures} · "
              f"tokens in/out: {s.prompt_tokens}/{s.completion_tokens} · failovers to backup host: {s.failovers}",
              "", f"Raw records: `{path.name}` · Metadata: `{metadata_path.name}`"]
    report = "\n".join(lines)
    (results_dir / f"run-{stamp}.md").write_text(report, encoding="utf-8")
    print("\n" + report)
```

- [ ] **Step 7: Update the bottom-of-file suite defaults**

Change the final `SUITE.update` to:

```python
SUITE.update(system=SYSTEM, score=score, generate=generate, libraries=["nepali"], task_seed=2082)
```

- [ ] **Step 8: Run the eval-harness tests**

Run: `uv run pytest tests/test_eval_harness.py tests/test_eval_summary.py -q`

Expected: PASS.

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add eval/run_eval.py tests/test_eval_harness.py tests/test_eval_summary.py
git commit -m "Eval: add interpreter conditions, repeats and metadata"
```

---

### Task 5: Document the new evaluation modes

**Files:**
- Modify: `README.md:40-50`, `README.md:180-190`

- [ ] **Step 1: Add the variance note after the Results intro**

Insert after the paragraph that explains ground truth and raw records:

```markdown
The table below is from single-run measurements. New runs can use `--repeat 3` to report
mean ± half-range and record the model, host and requested seed for every run. The held-out
suite remains a separate experiment.
```

- [ ] **Step 2: Add command examples**

Replace the two existing `eval/run_eval.py` examples with:

```bash
uv run python eval/run_eval.py --suite stdnum --limit 6 --label compiled --skill skills/<name>/server.py
uv run python eval/run_eval.py --suite stdnum --limit 6 --repeat 3 --interpreter \
  --label compiled --skill skills/<name>/server.py
uv run python eval/run_eval.py --suite global --limit 6 --label compiled --skill skills/<name>/server.py
```

Add after them:

```markdown
`--interpreter` adds two conditions: Python with the suite library importable, and Python with only
the standard library. It needs Docker and `zyven-sandbox:py312`. Every JSONL record carries the run
number, model, host, requested seed and token counts; `eval/results/run-<stamp>.json` holds the run
configuration.
```

- [ ] **Step 3: Verify the README renders and commands are accurate**

Run: `grep -n "repeat 3\|interpreter\|run-<stamp>.json" README.md`

Expected: the new lines are present.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Docs: describe interpreter and repeated-run evals"
```

---

### Task 6: Final verification and live smoke test

**Files:** none

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`

Expected: all tests pass (Docker-independent).

- [ ] **Step 2: Verify the interpreter tool works live (when Docker is available)**

Start Docker, build the image if needed, then run:

```bash
docker build -t zyven-sandbox:py312 zyven/sandbox
uv run python eval/run_eval.py --suite nepali --limit 1 --repeat 1 --interpreter --skip-baseline
```

Expected: `interpreter_lib` and `interpreter_no_lib` complete; the library variant can import
`nepali`; the no-library variant cannot. If Docker or the image is unavailable, record that the live
smoke test was skipped and keep the offline tests as the verification.

- [ ] **Step 3: Review the diff**

Run: `git diff --stat main...HEAD && git status --short`

Expected: only intended files changed; `.env` remains ignored and untracked.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "Eval: finish interpreter and variance verification"
```

Only commit if Step 1 or Step 3 produced changes.
