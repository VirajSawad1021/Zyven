# Changelog

## 0.2.0 (unreleased)

The first release after Frogtoberfest 2026. Zyven now works with any model or coding agent, checks MCP servers it did not
build, and installs without a clone.

### Added
- **Coding agents as compile roles.** Codex, Claude Code, Antigravity, OpenCode or the Qoder CLI can do any compile role,
  run headless with minimal tools (`zyven compile --agent codex`, `--compiler claude:opus --tester qoder`). The gates
  still decide. `provenance.json` records who did each role. (#54)
- **`zyven verify`**: outside-in checks for any MCP server, run over stdio, URL or the sandbox.
  - **Checks:** handshake, schemas, tool poisoning (invisible Unicode decoded), annotations, stability between
    connections and against a lock file (rug pulls), and robustness probes with input the schema forbids.
  - **Options:** `--docker`, `--allow-network`, `--markdown` and `--strict`.
  - (#55, #57, #60)
- **`zyven mcp`**: verified skills as a stdio MCP server for Claude Code, Codex and any agent, with no board running.
  `--print-config` prints the `claude`/`codex mcp add` commands. (#56)
- **Install with `uvx`/`pipx`**: `zyven setup` builds a sandbox image stamped with a hash of its files. `zyven doctor`
  reports what is missing, including a stale image. An installed copy keeps its data in `~/.zyven`. The board starts
  without a model key. There is also a release workflow for PyPI trusted publishing. (#57)
- **`zyven reassemble`**: rebuilds skills with the current harness and reruns all six gates, with no model calls. The old
  server is kept on any failure. (#58)
- **Connections run `zyven verify` on Test.**
  - A failing server needs an explicit "Turn on anyway".
  - Approved tool definitions are pinned, and a later change refuses the server at run time. (#59)
- **The repository is a GitHub Action** (`uses: VirajSawad1021/Zyven@...`) that writes the verify report to the job summary. (#60)
- **A mutation test of the gates** (`eval/mutation_test.py`): it breaks verified skills on purpose and counts what the
  gates catch.
- **`zyven export`**: a verified skill as a standalone MCP server, with a Dockerfile, the library pinned to the verified
  commit, and a README with the gate results and client config. The exported networkx skill was built, verified and
  called with no Zyven at run time.
- **`zyven verify --config` / `--discover`**: checks every server in Claude Desktop/Code, Cursor, Windsurf, VS Code,
  Gemini CLI or Codex configs. `env` values are passed to the server, never printed.

### Changed
- Compiled skills declare `read_only_hint` / `destructive_hint=False` / `open_world_hint=False`. Their input schemas carry
  parameter descriptions (`pydantic` joined the policy's framework list). Zyven's own skills now pass `zyven verify` with
  no warnings.
- Closed models are labelled `[closed model]`, not "experiment only". Coding agents are labelled `[coding agent]`. Published
  results stay open-weight, and the CI check now also scans per-role provenance.
- Every sandbox container gets the host name `zyven-sandbox`.

### Fixed
- **Source-root detection:** the analyzer picked `.` over `src/` when a stray package sat at the top (pypa/packaging's
  `tasks/`), so adapters imported `src.packaging...`. It now prefers the package that `pyproject.toml` names. (#54)
- **Leaked containers:** `verify` left sandbox containers running when a server ignored the end of its input. (#57)
- **`mcp --print-config` under uvx** pointed at a Python inside uv's cache. (#57)
- **A timing flake** in `test_connected_tools`: a 3 s connect timeout also timed out the healthy server. (#59)

## 0.1.0 (Frogtoberfest 2026)

The competition release:
- the capability compiler (five roles, six sandbox gates, bounded repair)
- the self-extending agent
- the unified dashboard and the Control center
- MCP connections with OAuth
- the Zyven hub
- open-model evaluations on stdnum, global calendars and phone numbers, Nepali dates, packaging and networkx
