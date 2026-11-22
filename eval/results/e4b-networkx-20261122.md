# Gemma 4 E4B on the networkx suite (2026-11-22)

Model: `gemma-4-e4b-it` (Gemma 4 E4B, a small open-weight model), served on a Kaggle T4 GPU. Suite: networkx, 4 tasks per
category, 24 tasks, the same tasks and output budget (4,096 tokens per model call) as the published 26B runs.

| Condition | shortest_path | components | mst_weight | max_flow | betweenness_top | triangle_count | Total | Avg sec/task |
|---|---|---|---|---|---|---|---|---|
| Model alone | 4/4 | 4/4 | 3/4 | 4/4 | 3/4 | 4/4 | **22/24** | 77.8 |
| Model + verified `graph_algorithms` skill | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | **24/24** | 12.9 |

The skill condition was run with the current `graph_algorithms` skill: every tool accepts edges written as `'A-B:3'` or
`'A->B:3'`, `count_connected_components` takes an optional node list, and tool error messages reach the model (all six
gates passed again; see the skill's `provenance.json`). The model-alone rows come from the same day's run with the same
tasks.

Raw records (48): `e4b-networkx-20261122.jsonl`.
