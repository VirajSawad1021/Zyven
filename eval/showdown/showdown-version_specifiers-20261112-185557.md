# Agent showdown: `version_specifiers` (2026-11-12)

Repository `packaging` at its pinned commit; one FIXED spec for everyone (no Architect), so only the Compiler, Tester and Repair vary; same gates. One run each: a sample, not a benchmark. Compiled skills were not committed.

| Contender | Verified | Attempts | Time | Tools kept | Dropped | Tester cases | Mutants caught | Cases calibrated |
|---|---|---|---|---|---|---|---|---|
| model (gemma-4-26b-a4b-it@generativelanguage.googleapis.com) | yes | 1 | 65 s | 3 | - | 12 | 12/14 | 0 |
| codex (Codex (its default model) [coding agent]) | yes | 1 | 61 s | 3 | - | 14 | 12/12 | 0 |

Survivors for model: compare_versions compare (line 4: Lt -> LtE); compare_versions negate_condition (line 9: condition negated)

## Reading this run (the fair one: one fixed design)
- **The spec is held fixed.** It is the 3-tool design from Codex's earlier run, so the Architect's run-to-run variation is
  taken out.
- **With the design fixed, the open model is close to Codex.** Both verified on the first attempt with all 3 tools, in
  about a minute. Gemma 26B's 12 cases caught 12/14 mutants of its own code (86%); Codex's 14 caught 12/12.
- **Gemma's two survivors** are `Lt -> LtE` (catching it needs `a_is_less` checked on equal versions) and one negated
  condition: the kind of gap the Tester coverage work (#62) targets.
- **For comparison, the first run** (before #62, with its own 4-tool design) gave Gemma 4 cases that caught 4/10. The
  design differs, so that is not a controlled before/after, but it is consistent with #62 helping.
- **One run each.** The mutant counts differ because each contender's own code is mutated.
