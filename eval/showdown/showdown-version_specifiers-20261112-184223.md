# Agent showdown: `version_specifiers` (2026-11-12)

Repository `packaging` at its pinned commit; every role played by the contender; same gates. One run each: a sample, not a benchmark. Compiled skills were not committed.

| Contender | Verified | Attempts | Time | Tools kept | Dropped | Tester cases | Mutants caught | Cases calibrated |
|---|---|---|---|---|---|---|---|---|
| model (see log) | no | - | 555 s | 3 | - | 0 | - | - |
| codex (Codex (its default model) [coding agent]) | yes | 1 | 135 s | 3 | - | 17 | 12/12 | 0 |

model did not verify. Last log lines:
```
[zyven] compiler.start: writing 3 tool bodies (gemma-4-26b-a4b-it@generativelanguage.googleapis.com)
[zyven] done: NOT VERIFIED: compiler: model call failed after retries: timeout after 240s: ReadTimeout('The read operation timed out')

verified: False
18:33:16 model call failed (timeout after 240s: ReadTimeout('The read operation timed out')); retry 1 in 1s
```

## Reading this run (rerun after #62's Tester coverage changes)
- **Gemma did not fail on quality.** Google AI Studio did not answer the Compiler role's call within 240 s, twice. So
  this run says nothing about #62's effect on Gemma's tests; it needs another attempt.
- **Before #62 merged, Zyven left no trace of this kind of failure.** A failed compile now keeps its `events.json` and
  `failure.json` (#65). This table's log lines came from the showdown's own capture.
- **Codex verified on the first attempt with all 3 tools, and its 17 cases caught 12/12 mutants.** In the first run it
  took 3 attempts and dropped one tool. Part of that may be #62 and part is run-to-run variation; one run each cannot
  tell them apart.
