# Changelog

## 0.2.0 (unreleased)

The first release after Frogtoberfest 2026. Zyven now works with any model or coding agent, checks MCP servers it did not
build, and installs without a clone.

### Added
- **SARIF output for `zyven verify`** (`--sarif FILE`, and a `sarif` output on the GitHub Action), so findings show up
  in GitHub code scanning.
  - Every finding has a stable rule ID, such as `descriptions/hide-from-user` or `stability/lock-mismatch`, with a
    level (error for failures, warning otherwise) and a fingerprint that stays the same between runs.
  - Results are attached to the lock file, or to the file named in the server command; with `--discover`, to each
    server's config file.
  - The JSON report now says, per check, how many findings are failures (`failing`).
- **`zyven verify` catches terminal escape sequences** in tool names, descriptions, parameters and server instructions.
  - Text hidden with SGR 8 is read back in the report.
  - It names cursor movement and erasing, OSC 8 hyperlinks with their real targets, OSC 52 clipboard writes,
    and stray control characters such as backspace.
  - Instruction patterns are also matched after escapes and invisible characters are stripped, so
    `ign<ESC>[0more previous instructions` no longer slips past.
- **Lock file version 2 and a `pinning` check** in `zyven verify`.
  - The lock now records the server's name and version, the launch command, the image ID under `--docker`, and the
    hosts reached under `--allow-host`.
  - A new version with identical tool definitions (the postmark-mcp pattern) is now a warning.
  - A renamed server fails.
  - `pinning` warns when `npx`, `uvx`, `pipx` or `docker run` would start whatever release is newest.
  - Version 1 lock files still work.
- **Hardened build and release.**
  - Every GitHub Action in CI, the release workflow and Zyven's own `action.yml` is pinned to a full commit SHA, so a
    moved tag cannot change what runs. Dependabot proposes the bumps.
  - Checkouts no longer keep the token. Release builds use no dependency cache. Step outputs reach scripts as
    environment variables.
  - A CI job audits the workflows with zizmor.
  - The PyPI upload publishes PEP 740 attestations through trusted publishing.
  - `SECURITY.md` explains how to report a vulnerability.
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
- **`zyven outdated`**: lists skills built from a library commit that upstream has moved past. With `--fetch` it
  also counts the commits behind and lists the changed files inside the modules each skill uses. The committed
  networkx skill was 29 commits behind, with 3 changed files in modules it uses. Nothing is recompiled
  automatically.

- **Network allowlist for the sandbox** (`zyven verify --docker ... --allow-host HOST`): an internal Docker network
  plus an egress proxy that forwards only to allowlisted hosts. Direct connections have no route. The report
  lists every refused host.
- **Compiled skills can have a host allowlist too** (`zyven compile --allow-host`, set by a reviewer, never a model).
  The gates run under it, it is recorded in provenance as `network_hosts`, and at run time `ToolBox` starts
  the skill's egress proxy with it. That covers the board's agent, the hub and `zyven mcp`.

### Changed
- Compiled skills declare `read_only_hint` / `destructive_hint=False` / `open_world_hint=False`. Their input schemas carry
  parameter descriptions (`pydantic` joined the policy's framework list). Zyven's own skills now pass `zyven verify` with
  no warnings.
- Closed models are labelled `[closed model]`, not "experiment only". Coding agents are labelled `[coding agent]`. Published
  results stay open-weight, and the CI check now also scans per-role provenance.
- Every sandbox container gets the host name `zyven-sandbox`.

### Fixed
- **Policy gate: attributes reached by a string.** `getattr(f, "__glo" + "bals__")` passed the static gate,
  because only written-out attributes were checked. `getattr` is now allowed only as a direct call with a literal,
  ordinary name; `attrgetter`, `methodcaller` and `__builtins__` are refused. The container was always the
  boundary, and the docs now say the gate is a filter.
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
