# Zyven

**Turn open-source code into verified skills that AI agents learn on demand and keep.**

Language models are confidently wrong about things that need exact logic: check digits, calendar
conversions, validation rules, lookups. The correct, tested code for these already exists in open-source
libraries, but an agent cannot use it until someone hand-builds a tool around it.

Zyven compiles repository functionality into **MCP tools** automatically and only hands a tool to an agent after
it has passed a set of checks in a locked-down sandbox, including the repository's own tests and
**differential tests against the library itself**.

> Frogtoberfest 2026 entry · Status: **capability compiler working end to end** on general-purpose libraries.
> Roadmap: [issues](https://github.com/VirajSawad1021/Zyven/issues).

## How it works

```
repo ──► Analyzer (AST, never executes repo code) ──► Scout (AI) ──► Architect (AI) ──► Compiler (AI) ──► Tester (AI)
          symbols, call graph, tests,                   which          tools, params,     tool bodies     library-reference
          doctests, side effects, license               capabilities   boundary, tests                    test cases (never
                                                                                                          sees the adapter)
                                         ▼
            Harness assembles the MCP server (signatures, per-tool imports, docstrings) + static policy check
                                         ▼
   Sandbox gates (Docker: no network · non-root · read-only · capabilities dropped · resource limits)
   policy · import · upstream tests · input robustness · MCP smoke · differential vs. library
                                         ▼
        fail ──► Repair (AI, bounded) ──► re-verify ──► still failing tools are dropped and recorded
        pass ──► skill package: server.py · capability.json · provenance.json · validation-report.json
```

The model proposes; the harness decides. Every symbol the model names is resolved against the static analysis
(invented names are rejected), generated code is policy-checked before it runs, and only observed sandbox results
mark a skill as verified, scoped to the named checks.

## Results

All runs use the open-weight model `gemma-4-26b-a4b-it`, the same tasks and budget in every condition, and ground
truth computed by the source library itself. Raw records are in `eval/results/`.

**Global standard numbers** ([python-stdnum](https://github.com/arthurdejong/python-stdnum), 366 modules):

| Condition | IBAN valid? | IBAN check digits | Card number passes Luhn? | Total |
|---|---|---|---|---|
| Model alone | 0/6 | 0/6 | 0/6 | **0/18** |
| Model + Zyven-compiled skills | 6/6 | 6/6 | 6/6 | **18/18** |

**Calendar and phone data** ([py-nepali](https://github.com/opensource-nepal/py-nepali); Bikram Sambat calendar):

| Condition | Date conversions + weekday + phone operator | Total |
|---|---|---|
| Model alone | 2/10 · 0/10 · 1/10 · 6/10 | **9/40** |
| Model + hand-written skill | 10/10 each | **40/40** |
| Model + Zyven-compiled skills | 10/10 each | **40/40** |

Without tools the model tries to compute checksums and calendars by hand and usually runs out of budget.

### What the gates caught during development
- **Differential gate:** merged imports in a generated server made the "Luhn" tool silently run another checksum
  algorithm. Every other gate passed; the library comparison failed 3 of 8 cases, and the build now scopes imports
  per tool.
- **Input robustness:** a card-number tool crashed on `4992 7398 71` (spaces); the Repair role fixed it.
- **Partial verification:** an IBAN check-digit tool that could not be repaired was dropped from the package
  instead of being shipped unverified.

## Usage

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker.

```bash
uv sync
cp .env.example .env                      # set MODEL_API_KEY for an open-weight model host
docker build -t zyven-sandbox:py312 zyven/sandbox

uv run zyven analyze path/to/repo         # deterministic analysis + rules-only baseline
uv run zyven scout   path/to/repo         # AI: capabilities worth compiling
uv run zyven compile path/to/repo --capability <name>
uv run zyven compile path/to/repo --capability iban --entry stdnum.iban.validate   # reviewer-set boundary

uv run python eval/run_eval.py --suite stdnum --limit 6 --label compiled --skill skills/<name>/server.py
```

## Working on large repositories
- **Tests:** pytest runs unittest suites, `*.doctest` files and docstring examples; gates report how many doctest
  examples were actually checked.
- **Digest folding:** families of modules sharing one API are folded for the model
  (python-stdnum: 182k → 37k characters; 237 validator modules in one block).
- **Human-set boundaries:** `--entry` overrides the Scout's choice of entry points.

## Repository layout

| Path | Contents |
|---|---|
| `zyven/analysis/` | analyzer, rules-only miner and digests, reference resolution |
| `zyven/ai/` | model provider, typed schemas, AI roles |
| `zyven/compiler/` | server assembly, static policy, verification gates, compile pipeline |
| `zyven/sandbox/` | Docker runner, image, in-container MCP smoke and differential test runners |
| `zyven/agent/` | MCP toolbox and tool-using agent loop |
| `toolkit/` | hand-written reference skill (baseline) |
| `eval/` | task suites, before/after runner, results |

## Models and sources

Only open-weight models, end to end; the endpoint is configurable (Google AI Studio, OpenRouter, Groq, local Ollama).

| Repo | Commit | License | Used as |
|---|---|---|---|
| [arthurdejong/python-stdnum](https://github.com/arthurdejong/python-stdnum) | `006192e` | LGPL-2.1 | wrapped (imported, not copied) |
| [opensource-nepal/py-nepali](https://github.com/opensource-nepal/py-nepali) | `3ff1947` | MIT | wrapped (imported, not copied) |

## License

MIT
