# Zyven: 3-minute demo script

Goal: show every part of the product once, in the order a user meets it. An agent lacks an exact capability, Zyven
compiles a verified tool from a real repository, and the same tool then serves other agents (Codex, OpenCode) and
connected services.

## Setup (before recording)

```bash
docker build -q -t zyven-sandbox:py312 zyven/sandbox       # once, after pulling
uv run zyven board --port 8767 --board-dir workspace/board-demo
```

- Open http://127.0.0.1:8767 in a clean browser window at 1280x720, light theme, zoom 110%.
- Docker Desktop running. Codex signed in (`codex login`) and turned on in the Control center.
- Notion signed in on the Connections page (or cut chapter 6).
- The graph question to use (from `eval/tasks_networkx.py`): "In this weighted graph, what is the shortest path
  length from A to H?" with an edge list of about 12 edges.
- The live compile takes several minutes. Record it once and speed that stretch up to about 10 seconds, labelled "sped up".
- Do not show `.env`, any key, or the terminal (except the `zyven board` line).
- Show open-weight results only. Label dev-only runs or leave them out.

## Chapters

| Time | Chapter | On screen | Narration file |
|---|---|---|---|
| 0:00-0:15 | Problem | Results page: a small open model alone gets 1/24 graph questions right | `00-problem.txt` |
| 0:15-0:50 | 1. Compiler | Repo, then Scout, Architect, Compiler, Tester, six gates turning green, skill page with provenance | `01-compiler.txt` |
| 0:50-1:10 | 2. Approval cards | The compile waits for a human yes; show approve | `02-approval.txt` |
| 1:10-1:35 | 3. Self-extending agent | Task the agent cannot do, gap found, catalog match, compile, answer | `03-agent.txt` |
| 1:35-2:05 | 4. Control center | Same task with Codex headless; run log; export folder | `04-control.txt` |
| 2:05-2:30 | 5. Zyven hub | Codex calling Zyven's verified tools with no key of its own | `05-hub.txt` |
| 2:30-2:50 | 6. Connections | Notion sign-in, connector card, agent reads a page (Slack and Google Docs listed) | `06-connections.txt` |
| 2:50-3:05 | 7. Safety | Local-only guard, per-run tokens, full access needs two switches (do not turn it on) | `07-safety.txt` |
| 3:05-3:20 | Value | Results: 1/24 alone, 19/24 with the skill; repo URL | `08-value.txt` |

Narration text lives in `docs/narration/`. Each file is one chapter, so one chapter can be re-recorded alone.

## Fallbacks

- If the live compile fails, use the recorded timeline or the screenshots in `docs/screenshots`.
- If Notion is not signed in, cut chapter 6 and give its seconds to chapter 4.
- Export at 1080p, under 3:30, with burned-in captions in case it plays muted.
