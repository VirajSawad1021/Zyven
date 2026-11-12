# Tester coverage change: does it catch more mutants? (2026-11-10)

**Short answer: not yet.** The deterministic parts of the change are improvements. The prompt part has not shown a gain.

## Setup
- **The question.** The mutation test (`mutation-20261106-222233.md`) found 5 bugs the gates missed. Each one sat where no
  Tester case looked. This change asks the Tester for coverage (every optional parameter, every return field, boundary
  inputs), checks it with `coverage_gaps()`, and sends one targeted follow-up.
- **The cases.** New ones were written by `gemma-4-26b-a4b-it` for copies of two verified skills. One new case failed on
  the *unmutated* skill. Its reference computed `str(a < b)` (`"True"`) for a field that holds `"less_than"`, and it was
  dropped, as is standard: a case must pass on the original program.
- **The mutants.** The same 20 mutants (seed 1, 6 per tool) were run against the old cases and the new ones, with the
  control passing before and after each run.

## Result: `version_specifiers`

| Cases | Written by | Coverage gaps | Killed |
|---|---|---|---|
| old | Codex | 4 | **18/20** |
| new | Gemma 26B + coverage prompt | 0 | **17/20** |

Both sets miss:
- **`Gt -> GtE`.** Catching it needs `a_is_greater` checked on equal versions.
- **An `Or -> And` that changes nothing observable.**

The new set also misses **`sort_versions IsNot -> Is`**. Every new `sort_versions` reference had a syntax error, so that tool
had no usable case. Two different models wrote the two sets, so this compares more than the prompt.

## `graph_algorithms`
- **The new cases.** Gemma 26B produced no usable case for 4 of the 6 tools, even after the targeted follow-up. The
  original cases came from Gemma 31B.
- **What the first attempt exposed.** Gemma's quota had run out and the missed-tools request returned nothing, yet the
  first version of `coverage_gaps` reported "full coverage", because it skipped tools with no cases. That is fixed.

## Follow-up: re-ask after the sandbox's own checks, and "leave it out once" (same day)
- **Why the first attempt stalled.** The one survivor the new cases added was `sort_versions IsNot -> Is`. That mutant
  raises an error whenever `descending` is *omitted*, and the only usable case *set* `descending=False`. The case that left
  it out had a syntax error, and it still counted as coverage.
- **The fixes.**
  - Coverage is judged only on cases that pass the sandbox's reference checks (`reference_problem`, shared with `verify`).
  - Every optional parameter must also be **left out** in at least one case.
  - Tools that still have gaps are asked about again, with the rejection reasons quoted.
- **The new cases.** Gemma 26B wrote 17 cases. Calibration dropped one, again `str(a < b)` for a field holding `"less_than"`:
  `mutation_test.py --calibrate` removes cases that fail on the unmutated skill and reports each one.

| Cases | Written by | Killed (same 20 mutants) |
|---|---|---|
| old | Codex | 18/20 |
| new, first attempt | Gemma 26B | 17/20 |
| **new, with the follow-up** | **Gemma 26B** | **18/20** |

**What is left.**
- **`Gt -> GtE`.** Catching it needs `a_is_greater` checked on equal versions. The prompt now asks for that, and the model
  has not done it yet.
- **An equivalent `Or -> And`.**

So the follow-up brings a smaller open model to parity with Codex here, and closes the gap it targeted. It has not gone
beyond Codex yet.

## What this changes
- **Kept: deterministic, and clear improvements.**
  - Tools with no case count as gaps.
  - Reference programs ending in `print(...)` are rejected; they always evaluate to `None`.
  - Gaps are reported in the compile log.
- **Unproven: the coverage prompt.** On a small model it raised coverage on paper and lowered case quality.
- **Next.** Re-ask when a tool has no valid case *after the sandbox's own checks* (syntax, policy, invalid references).
  Today the follow-up only sees the Tester's own filter.
