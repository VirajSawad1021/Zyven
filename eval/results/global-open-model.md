# Global suite with an open-weight model

Model: `gemma-4-26b-a4b-it` (open weights) for compiling skills and for the agent. 30 tasks, 6 per category,
ground truth computed by hijridate, pyluach and phonenumbers. Same 4,096-token budget and one-time
"answer now" retry rule in both conditions.

| Condition | Hijri → Gregorian | Gregorian → Hijri | Jewish holiday | Phone valid? | Phone → E.164 | Total | Avg s/task |
|---|---|---|---|---|---|---|---|
| Model alone | 2/6 | 3/6 | 3/6 | 5/6 | 5/6 | **18/30 (60%)** | 80.7 |
| Model + Zyven-compiled skills | 6/6 | 6/6 | 3/6 | 6/6 | 6/6 | **27/30 (90%)** | 37.9 |

Skills available in the second condition (compiled and verified with the same open model):

| Skill | Source | Verified for |
|---|---|---|
| Hijri ↔ Gregorian conversion | hijridate `f6f0f4f` (MIT) | policy, import, 5,903 upstream tests, input robustness, MCP smoke (the differential gate did not run: the Tester call failed on this compile) |
| Phone parsing and formatting | phonenumbers `e921470` (Apache-2.0) | policy, import, upstream tests, input robustness, MCP smoke, differential |

There is **no compiled Jewish-holiday skill** in this run: the Architect call for pyluach timed out on the hosted
endpoint three times (once with a reviewer-narrowed boundary). The holiday category therefore ran without a skill
in both conditions; its three misses ran out of budget answering alone. With a different model host the same
capability compiles and verifies (development run, not part of these results).

Raw records: `run-20261014-160438.jsonl` (model alone), `run-20261014-163640.jsonl` (with skills; summary in
`run-20261014-163640.md`).
