# Eval interpreter baseline and run-to-run variance

**Issues:** #24, harness portion of #25
**Status:** approved design, pending implementation
**Date:** 2026-10-22

## Goal

Make the evaluation runner answer two reviewer questions:

1. Does the model do better when it can write and run Python, with or without the source library?
2. Are the reported numbers stable across repeated runs?

The held-out suite and refreshed three-run README table are explicitly out of scope for this pass. They remain part of issue #25.

## Interpreter condition

Add `eval/interpreter.py` with a `PythonToolBox` that exposes exactly one tool, `run_python(code)`.
It reuses `zyven.sandbox.runner.run`, so every execution inherits the existing sandbox policy:
Docker, no network, non-root, read-only root, dropped capabilities, CPU/memory/process limits.

Code is passed as a single argv element to `python -c`; the runner does not write model code to a
host bind mount.

Two conditions are available:

- `interpreter_lib`: the suite's source packages are mounted read-only under `/libs/<n>/<package>`
  and their parents are added to `PYTHONPATH`.
- `interpreter_no_lib`: no package mounts and no extra `PYTHONPATH`; only the standard library is
  available.

Default packages:

| Suite | Packages |
|---|---|
| `nepali` | `nepali` |
| `stdnum` | `stdnum` |
| `global` | `hijridate`, `pyluach`, `phonenumbers` |

`--library` (repeatable) overrides the defaults. Packages are resolved from the active `uv`
environment, which already pins them in `pyproject.toml`. A missing package is a startup error, not
a silent fallback.

The system prompt gets a short interpreter hint. The library variant names the importable packages;
the no-library variant says only the standard library is available and packages cannot be installed.
All other prompts, tasks, ground truth, `MAX_TOKENS`, and the six-step agent budget stay the same.

## Repeated runs and metadata

New CLI options:

- `--interpreter`: run both interpreter conditions in addition to the selected baseline/skill work.
- `--repeat N`: run each condition N times. Default `1`.
- `--seed S`: request model seed S for the first repeat and S + (run number - 1) thereafter. Default none.
- `--task-seed S`: override the suite's frozen task-generation seed.

Every JSONL record adds `run`, `model`, `host`, `seed`, `tokens_in`, and `tokens_out`.
`ChatResult` and `AgentResult` gain prompt/completion token counters so per-task token use is exact
when the host returns usage data.

A sidecar `run-<stamp>.json` records suite, model, host, task seed, requested model seed, repeat count,
condition labels, output budget, and timestamp.

## Summary format

Summaries are computed per run, then aggregated. For N > 1, each accuracy cell is reported as
`mean% ± half-range%`; for N = 1 it is just `mean%`. The table includes:

- accuracy by category and overall;
- number of runs;
- answer-now retries, hit-cap count, and API errors;
- average seconds per task;
- tokens per task.

Half-range is `(max - min) / 2` across runs, so the interval covers the observed run values. API
errors remain excluded from accuracy, as in the current report.

## Testing

Offline tests, no Docker or network:

- `PythonToolBox` invokes the sandbox with no network, passes code via `python -c`, mounts only the
  requested package directories, and truncates large output.
- Invalid tool names and empty code return tool errors rather than crashing the agent loop.
- Seed is included in the provider request and token usage is exposed on `ChatResult`.
- Repeated-run summaries produce the expected mean and half-range.

The live interpreter smoke test is optional and requires Docker plus `zyven-sandbox:py312`.

## Non-goals

- Selecting and freezing a held-out library.
- Compiling a new skill for that library.
- Replacing the existing single-run results table with three-run ranges.
