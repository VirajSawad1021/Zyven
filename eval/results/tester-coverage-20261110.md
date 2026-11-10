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

## What this changes
- **Kept: deterministic, and clear improvements.**
  - Tools with no case count as gaps.
  - Reference programs ending in `print(...)` are rejected; they always evaluate to `None`.
  - Gaps are reported in the compile log.
- **Unproven: the coverage prompt.** On a small model it raised coverage on paper and lowered case quality.
- **Next.** Re-ask when a tool has no valid case *after the sandbox's own checks* (syntax, policy, invalid references).
  Today the follow-up only sees the Tester's own filter.
