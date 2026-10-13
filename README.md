# Zyven

**Turn open-source code into verified skills that local AI agents learn on demand and keep.**

Agents can only use tools someone hand-built. Huge amounts of correct, tested code already exist in open-source
repositories, but agents cannot use them without manual integration work. Zyven's goal is to compile repository
functionality into MCP tools, verify them in a sandbox against the repository's own tests, and hand them to an
agent that keeps what it learns.

> Frogtoberfest 2026 entry · **Status: foundation (stage 1 of the build).** The capability compiler, the
> self-extending agent and the task board land in later commits.

## What this stage contains

| Component | Path |
|---|---|
| Model provider for any OpenAI-compatible host serving an **open-weight** model (retries with backoff, timeout handling, schema-validated JSON output, inline-reasoning stripping, optional fallback host) | `zyven/ai/provider.py` |
| MCP toolbox: connect to skill servers over stdio, expose their tools to the model, add tools mid-run | `zyven/agent/mcp_tools.py` |
| Tool-using agent loop | `zyven/agent/loop.py` |
| Docker sandbox runner: no network, non-root, read-only filesystem, all capabilities dropped, CPU/memory/process/time limits; runs a repo's tests with pytest | `zyven/sandbox/runner.py`, `zyven/sandbox/Dockerfile` |
| MCP protocol smoke tester (runs inside the sandbox) | `zyven/sandbox/mcp_smoke.py` |
| Hand-written reference skill for [py-nepali](https://github.com/opensource-nepal/py-nepali): Bikram Sambat ↔ Gregorian dates, weekday, Nepali phone numbers | `toolkit/py_nepali_manual/server.py` |
| Before/after evaluation: 40 Nepali tasks with ground truth computed by py-nepali itself | `eval/` |

## First result: the baseline the compiler has to match

Same open-weight model (`gemma-4-26b-a4b-it`), same 40 tasks, same 4,096-token budget per call, same one-time
"answer now" retry rule in both conditions. Raw records: `eval/results/run-20261012-195903.jsonl`.

| Condition | AD→BS | BS→AD | BS weekday | Phone operator | Total |
|---|---|---|---|---|---|
| Model alone | 2/10 | 0/10 | 1/10 | 6/10 | **9/40 (22%)** |
| Model + hand-written py-nepali skill | 10/10 | 10/10 | 10/10 | 10/10 | **40/40 (100%)** |

Without a tool the model tries to work out the Nepali calendar by hand and usually runs out of budget before
answering. With the skill it answers in about 15 s per task. The next stage makes Zyven produce such skills
automatically from the repository and verify them.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
cp .env.example .env            # then set MODEL_API_KEY (open-weight model host)
docker build -t zyven-sandbox:py312 zyven/sandbox
```

## Run

```bash
# The hand-written skill as an MCP server (stdio)
uv run python toolkit/py_nepali_manual/server.py

# Before/after evaluation (writes eval/results/run-<time>.jsonl and .md)
uv run python eval/run_eval.py --limit 10
```

## Models

Only open-weight models, end to end. Development used `gemma-4-26b-a4b-it` (Gemma license) through an
OpenAI-compatible endpoint; the endpoint is configurable (Google AI Studio, OpenRouter, Groq, or local Ollama).

## Source repositories

| Repo | Commit | License |
|---|---|---|
| [opensource-nepal/py-nepali](https://github.com/opensource-nepal/py-nepali) | `3ff1947` | MIT |

## License

MIT
