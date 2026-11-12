# Agent showdown: `version_specifiers` (2026-11-12)

Repository `packaging` at its pinned commit; every role played by the contender; same gates. One run each: a sample, not a benchmark. Compiled skills were not committed.

| Contender | Verified | Attempts | Time | Tools kept | Dropped | Tester cases | Mutants caught | Cases calibrated |
|---|---|---|---|---|---|---|---|---|
| model (gemma-4-26b-a4b-it@generativelanguage.googleapis.com) | yes | 1 | 109 s | 1 | - | 2 | 4/6 | 0 |

Survivors for model: parse_version off_by_one (line 13: 1 -> 2); parse_version off_by_one (line 13: 1 -> 2)

## Reading this run (Gemma alone, retried after a host timeout)
- **Verified first time, but on a different capability shape.** This time the Architect designed one tool
  (`parse_version`); earlier runs had 3 or 4. Its 2 cases caught 4/6 mutants, and both survivors are an off-by-one on a
  line those cases never reach.
- **The Architect's choices vary between runs more than the effect being measured.** A fair comparison of test quality
  has to hold the spec fixed and vary only the Compiler and Tester: `eval/showdown.py --spec` does that.
