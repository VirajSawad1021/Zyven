# Agent showdown: `version_specifiers` (2026-11-12)

Repository `packaging` at its pinned commit; every role played by the contender; same gates. One run each: a sample, not a benchmark. Compiled skills were not committed.

| Contender | Verified | Attempts | Time | Tools kept | Dropped | Tester cases | Mutants caught | Cases calibrated |
|---|---|---|---|---|---|---|---|---|
| model (gemma-4-26b-a4b-it@generativelanguage.googleapis.com) | yes | 3 | 520 s | 2 | parse_version | 4 | 4/10 | 0 |
| codex (Codex (its default model) [coding agent]) | yes | 3 | 224 s | 3 | sort_versions | 9 | 16/16 | 0 |
| qoder (see log) | no | - | 48 s | 0 | - | 0 | - | - |

Survivors for model: compare_versions compare (line 18: GtE -> Gt); compare_versions drop_statement (line 55: statement dropped: op = '>='); compare_versions negate_condition (line 18: condition negated); compare_versions negate_condition (line 72: condition negated); compare_versions negate_condition (line 69: condition negated); compare_versions negate_condition (line 9: condition negated)

qoder did not verify. Last log lines:
```
[zyven] architect.start: Python Versions and Specifiers (Qoder CLI (its default model) [coding agent])
[zyven] done: NOT VERIFIED: architect: structured output invalid after 2 repairs: 1 validation error for CapabilitySpec
  Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value="You've reached your cred...Issue (input /feedback)", input_type=s

verified: False
```

## Reading this run
- **Qoder did not lose on quality: it was out of credits.** Its reply was an account message ("You've reached your credit
  limit…"), which the compile reported as invalid JSON. Agent replies like that are now reported as "usage limit"
  (`is_limit_reply` in `zyven/ai/agent_provider.py`).
- **Both other contenders produced verified skills.** Each dropped one tool it could not verify (partial verification).
- **The difference is in the tests each wrote.** Codex's 9 cases caught all 16 deliberate bugs. Gemma's 4 cases caught 4 of
  10; every survivor is a condition inside `compare_versions` that none of its cases reached.
- **This Gemma run predates the Tester coverage changes** (#62: coverage gaps, re-ask after the sandbox's checks, optional
  parameters left out once). Rerunning after #62 is the obvious next measurement.
- **One run each.** Model output varies between runs (see `eval/results/tester-coverage-20261110.md`).
