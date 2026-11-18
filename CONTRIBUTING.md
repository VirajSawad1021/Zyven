# Contributing to Zyven

Contributions are welcome: catalog libraries, checks for `zyven verify`, reports of false alarms, docs and code.
Security problems go through [SECURITY.md](SECURITY.md), which explains how to report them privately. Never open a
public issue for a security problem.

## Set up

Requirements:
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Docker
- Node 20+ (optional, only to build the web site)

```bash
git clone https://github.com/VirajSawad1021/Zyven.git && cd Zyven
uv sync
uv run zyven setup        # builds the sandbox image (Docker must be running)
uv run zyven doctor       # what is ready and what is missing
```

A model key is not needed for tests or for `zyven verify`. It is needed only to compile skills with the chat-model
roles. To use those roles, copy `.env.example` to `.env` and set `MODEL_API_KEY`.

## Run the checks CI runs

| Command | What it does |
|---|---|
| `uv run pytest -q tests` | Runs the unit tests. Docker is not needed; tests that need Docker or a library are skipped. |
| `uv run pytest -q tests/test_sandbox.py tests/test_egress.py` | Runs the sandbox tests. Docker must be running. |
| `uv run python -m compileall -q zyven eval toolkit scripts` | Checks that everything compiles. |
| `uv run python scripts/check_open_models.py` | Checks that committed results, configs and skill provenance use open-weight models only. |
| `uvx zizmor@1.32.0 --offline --min-severity medium .github/workflows action.yml` | Audits the GitHub workflows. |

## Ways to contribute

### Add a library to the catalog

The catalog is `catalog/repos.json`. Each entry has:
- `name`
- `url`
- `commit`: a full commit SHA, never a branch
- `license`
- `note`: one line

Zyven only ever fetches what is listed there, at that commit. Add the entry and run `uv run zyven sync` to clone it.
In the pull request, say why the library is a good fit. Pure functions with exact answers (checksums, calendars,
parsing, formatting) work best. Libraries that need the network, files, or a running service do not fit.

### Add or improve a check in `zyven verify`

The checks live in `zyven/mcpverify/checks.py`. The patterns for text aimed at the model are the
`INSTRUCTION_PATTERNS` list near the top. Every finding needs a stable rule ID in the `RULES` list of
`zyven/mcpverify/sarif.py`; a test fails if a finding falls back to a `/other` rule.

Add a test in `tests/test_mcpverify.py` that shows the new check catching something, and one that shows ordinary text
is not flagged. Test servers live in `tests/fixtures/mcp_servers/` (`good.py`, `poisoned.py`). A check that flags
honest servers does more harm than good: say what it could wrongly flag.

### Report a false alarm

If `zyven verify` flags something that is fine, open an issue with:
- the server (package and version)
- the exact finding line from the report
- why it is wrong

False alarms are bugs.

### Docs and code

Small, focused pull requests are easiest to review.

## Pull requests

- One topic per pull request, on its own branch.
- Tests for new behaviour, and `uv run pytest -q tests` passing.
- An entry in `CHANGELOG.md` under the unreleased version, saying what changed for a user.
- Claims need evidence. If a change makes something faster, safer or more accurate, include the numbers and how they
  were measured. `LIMITATIONS.md` says what Zyven does not do; update it when that changes.
- Never commit keys, tokens or `.env`.
- Style: type hints, short docstrings, lines up to 120 characters, plain language in docs and messages.
