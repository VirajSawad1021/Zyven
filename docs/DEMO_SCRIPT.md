# Zyven: 60-second demo script

Goal: show the whole loop once. An agent lacks a capability, Zyven compiles a verified tool from a real
repository, and the agent then answers correctly.

## Setup (before recording)

```bash
uv run zyven board --port 8767 --board-dir workspace/board-open
```

- Open http://127.0.0.1:8767 in a clean browser window at 1280x720, light theme, zoom 110%.
- Use the clean board (`workspace/board-open`), not the older 8766 board.
- Pre-warm Docker (Docker Desktop running) so the sandbox starts quickly, and rebuild the image once
  (`docker build -q -t zyven-sandbox:py312 zyven/sandbox`).
- The compile step takes several minutes live. Record it once, then speed that stretch up to about 8 seconds
  in the edit and label it "sped up".
- Task to give the agent: "In this weighted graph, what is the shortest path length from A to H?" with an edge list of about 12 edges
  (from `eval/tasks_networkx.py`). A small model gets this wrong or runs out of tokens working it by hand.

## Shots

| Time | Screen | Voice-over (about 150 words in total) |
|---|---|---|
| 0:00-0:06 | Landing page, then Board | "Language models are unreliable at exact things: calendars, versions, ID checksums. Zyven turns a real open-source library into a verified tool an agent can call." |
| 0:06-0:14 | Control center: create a Zyven run with the task above | "I give the agent a task. It first checks whether it already has a tool for it." |
| 0:14-0:22 | Board card: gap check says "no matching skill", catalog match found (networkx), approval request appears | "It finds a gap, matches the pinned repository in the catalog, and asks me to approve. Nothing is compiled without a human saying yes." |
| 0:22-0:38 | Click Approve. Show the compile timeline: Scout, Architect, Compiler, Tester, then the six gates turning green (policy, import, upstream tests, input robustness, MCP smoke, differential) | "Approved. Zyven reads the repository, designs the tool boundary, writes the adapter, and runs it through six checks in a Docker sandbox, including the library's own tests. Only a tool that passes is kept." (sped up) |
| 0:38-0:48 | Skill detail page: provenance (repo, pinned commit, license), validation report | "Every skill records its source, pinned commit, license and the checks it passed." |
| 0:48-0:56 | Agent answer on the board card, tool calls visible | "Now the agent calls the compiled tool and answers from the library, not from memory." |
| 0:56-1:00 | Insights/results page: "18/30 alone, 27/30 with compiled skills" (global suite) | "On our evaluation, an open model gets 60 percent alone and 90 percent with compiled skills. Zyven: tools that are verified, not trusted." |

## Notes for the recording

- Do not show `.env` or any key. Keep the terminal out of frame, or show it only for the `zyven board` line.
- Use only open-weight model results on screen. Label dev-only runs, or leave them out.
- Use the `graph_algorithms` skill (networkx, six gates passed) for the green-gates shot. It is already compiled in
  `skills/`, so the live compile can be replaced by its recorded timeline if the model host is slow.
- Export at 1080p, under 60 seconds, with burned-in captions in case it plays muted.
