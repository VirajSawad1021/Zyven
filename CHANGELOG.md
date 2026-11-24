# Changelog

## 0.2.0 (unreleased)

The first release after Frogtoberfest 2026. Zyven now works with any model or coding agent, checks MCP servers it did not
build, and installs without a clone.

### Added
- **sympy calculus and equation solving verify.** `skills/symbolic_calculus` (differentiate, integrate; 528 upstream
  tests, differential 18/18 plus generated) and `skills/equation_solving` (one equation or a system; 335 upstream tests,
  differential 15/15 plus generated), compiled through OpenCode by Reflection Beam 1.0 (501B, open weights) with
  DeepSeek V4.1 Flash as the Tester. Every tool passed all six gates; none was dropped.
- **sympy verifies: limits, simplify and factor.** `skills/symbolic_math` (sympy `16fa855`), compiled through OpenCode by
  Reflection Beam 1.0 (501B, open weights) with DeepSeek V4.1 Flash as the Tester. Two tools pass all six gates: 762
  upstream tests, differential 19/19 plus generated cases. Two more tools (equation solving, calculus) did not verify
  and were left out, as the compiler does with any tool it cannot verify.
- **The upstream-test gate counts only failures that concern the wrapped code.** The analyzer records which library
  functions each test calls, and pytest reports which tests failed. A failing test that is known not to call any wrapped
  function is listed in the gate's detail instead of failing it; a file that does not load, a test that cannot be
  mapped, or a test that calls wrapped code still fails it, and at least one test must reach the wrapped functions.
  One unrelated failing test is what kept sympy from verifying.
- **Verified dateutil and pint skills, and a small model gets 101 of 102 across four suites.** `date_arithmetic`
  (python-dateutil 4.0.0) and `unit_conversion` (pint 0.26.2), compiled through OpenCode by Reflection Beam 1.0 (501B,
  open weights) with DeepSeek V4.1 Flash as the Tester, all six gates. With the verified skills, Gemma 4 E4B answered
  24/24 date questions (11/24 alone), 29/30 unit conversions (22/30), 18/18 IBAN and Luhn checks (6/18) and 30/30
  calendar and phone questions (10/30) (`eval/results/e4b-four-suites-20261124.md`). New suites:
  `run_eval --suite dateutil|pint`. The stdnum skills are now in `skills/`. Closes #100.
- **Verified Jewish holidays and fast days skill (pyluach).** Four tools (holiday, festival, fast day, Shabbat for a
  date), compiled through OpenCode by Reflection Beam 1.0, a 501B open-weight model, and verified by all six gates:
  45 upstream tests, differential 41/41 Tester cases plus generated ones. Closes #99.
- **Coding-agent compiles can count as open-weight.** When OpenCode's model catalogue marks the chosen model as open
  weights, provenance names it (`opencode/beam-free = reflection/beam-1.0-501b-a23b`) and the open-model check accepts
  it; any other agent run is still labelled a plain coding agent.
- **Checked on 23 popular community MCP servers.** 22 started in the sandbox, 21 passed (348 tools, 119 called);
  the archived Slack reference server accepts invalid input (`eval/results/verify-community-20261124.md`).
- **`zyven verify --call read-only|all`: check what tools do, not only what they say.** Each tool is called four times
  with valid sample input from its schema. The results are scanned like descriptions (now including instructions in
  HTML comments), credentials in output are reported masked (tokens, API keys, passwords), and the tools are listed
  again afterwards to catch a rug pull that waits for a few uses. `read-only` calls only tools that declare
  `readOnlyHint`; `all` calls every tool and runs only in the sandbox. On Damn Vulnerable MCP Server, 7 of 15
  challenges fail and 3 more show their risky capability; the seven official servers still pass with every tool called
  (`eval/results/verify-dvmcp-20261124.md`).
- **`zyven verify` lists what each tool can do from its name and parameters.** Runs shell commands, runs code it is
  given, reads or writes files at a path the caller chooses, contacts a host the caller chooses, takes a password or
  token, runs database queries. These are listed as capabilities, not failures. A tool marked read-only whose name and
  parameters say it runs commands or writes files fails the annotations check. The seven official reference servers
  still pass, and their listed capabilities match what they do (filesystem reads and writes files, fetch contacts URLs).
- **`zyven verify` names tool shadowing and message redirection.** A description that tells the model how to use
  another tool ("when send_message is invoked ...") or sends messages to a fixed address or number is now reported
  by name, and "don't notify the user" counts as hiding. On the three published Invariant Labs proof-of-concept
  servers every attack is named; the seven official reference servers (55 tools) still pass
  (`eval/results/verify-real-world-20261123.md`).
- **Verified calendar and phone skills in `skills/`.** Hijri ↔ Gregorian conversion (hijridate) and phone number
  parsing and formatting (phonenumbers), compiled with an open model; all six gates pass. The Hijri tools also accept a
  date written with the month by name ("2 Shawwal 1418"), checked by 16 new differential cases. With them, the small
  open model Gemma 4 E4B answered 24/24 calendar and phone questions (8/24 alone)
  (`eval/results/e4b-global-20261122.md`).
- **Compiled skills get the imports their code needs.** When a tool's import list names a symbol
  (`pyluach.dates.GregorianDate`) instead of an import, or the code uses a library module or one of the spec's symbols
  without importing it, the harness adds the import. Only the library's own modules are added, so the policy gate
  sees nothing new. Small models often leave these out.
- **Compiled tools explain what was wrong with their input.** The MCP SDK passes only `ToolError` messages to the
  model, so a tool's own message ("each edge must have at least two nodes") arrived as a bare "Error executing tool".
  The harness now wraps every tool so its message reaches the model, which can then fix its call. Existing skills get
  it through `zyven reassemble`.
- **The graph skill takes edges the way questions write them, and isolated nodes.** Every graph tool also accepts
  `'A-B'` and `'A-B:3'`, and `count_connected_components` takes an optional node list, so nodes with no edges count as
  components, and `'A->B:3'` for directed graphs. Four differential cases cover them; all six gates passed again.
  With these changes, the small open model Gemma 4 E4B answered 24/24 graph questions with the skill (22/24
  alone) at 12.9 s per task instead of 77.8 s (`eval/results/e4b-networkx-20261122.md`).
- **`zyven verify --connection NAME`.** Checks a server connected on the board, signed in: with its stored API key, or
  its OAuth sign-in (Notion, Google Docs, ...), so hosted servers behind a login can be verified too. The tokens are
  used through the board's own store and refreshed there, never copied, so the board stays signed in.
- **`zyven verify --findings-csv FILE`.** Appends one row per finding (server, check, rule ID, level, text and an empty
  label column) to a CSV file, also with `--discover` and `--config`, for labelling findings by hand to measure how
  precise each rule is. Rows use the same rules and levels as the SARIF output.
- **`zyven verify --srt-settings FILE`.** After a check in the sandbox with `--allow-host`, writes a settings file for
  Anthropic's sandbox-runtime that allows only the hosts the server reached, no writes and no reads of credential
  folders, to run the server afterwards with least privilege. Without a network observation it writes nothing and
  says why.
- **A pre-commit hook** (`zyven-verify`): committing an MCP client config (`.mcp.json`, `.cursor/mcp.json`,
  `.vscode/mcp.json`, `claude_desktop_config.json`, `.codex/config.toml`) checks every server in it. Behind it,
  `zyven verify --files FILE...` treats its arguments as config files.
- **Compiles record how independent the Tester was.** `provenance.json` now has each role's model family and
  `tester_independence` (same model, same family, different family, or unknown), and a compile logs a warning when the
  Tester comes from the Compiler's own family. Models of one family share more errors, and a misreading the Tester and
  Compiler share is the differential gate's known blind spot. Use `--tester` with a model from another family.
- **Generated cases in the differential gate.** A Tester reference written with `{arg}` placeholders is reused on up
  to 12 more argument sets per tool, mixed from the Tester's values and small changes of them (seeded, no model).
  Inputs the library rejects, and inputs the tool declines (it raises, or answers with an error or `is_valid: False`),
  are not scored; any other disagreement fails the gate. Every skill saved so far still passes, with no false reject.
  On five skills and the same 96 mutants, the gates caught 81 instead of 80 (eval/results/mutation-20261118-*): a
  small gain, because most survivors sit where no Tester value reaches (an option no case sets, a field no case compares).
  `eval/mutation_test.py --generated 0` turns them off, to measure what they add. Existing installs pick up the new
  checker after `zyven setup`, which rebuilds the sandbox image.
- **`zyven verify --probe` reads what tools return.** A new `results` check scans the text of every probe call's
  result and error message with the description rules, since tool output reaches the model too. Probes send only
  input the schema forbids, so normal results are not seen; that is stated in the report.
- **SARIF output for `zyven verify`** (`--sarif FILE`, and a `sarif` output on the GitHub Action), so findings show up
  in GitHub code scanning.
  - Every finding has a stable rule ID, such as `descriptions/hide-from-user` or `stability/lock-mismatch`, with a
    level (error for failures, warning otherwise) and a fingerprint that stays the same between runs.
  - Results are attached to the lock file, or to the file named in the server command; with `--discover`, to each
    server's config file.
  - The JSON report now says, per check, how many findings are failures (`failing`).
- **`zyven verify --discover` / `--config` checks across servers.** A new `cross-server` warning when two servers offer
  the same tool name, or when one server's text names another server's tool (`send_email` in a calculator's
  description), which is how tool shadowing works. Plain words such as `search` are not counted as tool names.
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
- **Connection secrets are encrypted, with the key in the system keychain.** API keys and OAuth tokens move from a
  plain `connection-secrets.json` into `connection-secrets.enc` (Fernet), whose 44-character key lives in Windows
  Credential Manager, the macOS Keychain or the Linux Secret Service. The keychain cannot hold the tokens themselves:
  Windows refuses a value of about 2.4 KB. An existing plain file is migrated on first use and removed only after the
  encrypted copy reads back. Without a keychain the plain file is kept. New dependency: `keyring`.
- **`zyven verify` separates findings from capabilities.** A finding is evidence of deceit: hidden text, text that
  addresses the model about its own behaviour, or changed definitions. A capability is what a server can do or
  touches: a description naming a credential file, a secret or a URL, a destructive or open-world tool, a host it
  reached. Capabilities are listed (and are SARIF notes) but no longer fail a server, so an honest SSH or HTTP tool
  passes. Next to a model-directed instruction they are still findings, as its payload. A long base64-like blob on
  its own is now a warning.
- Compiled skills declare `read_only_hint` / `destructive_hint=False` / `open_world_hint=False`. Their input schemas carry
  parameter descriptions (`pydantic` joined the policy's framework list). Zyven's own skills now pass `zyven verify` with
  no warnings.
- Closed models are labelled `[closed model]`, not "experiment only". Coding agents are labelled `[coding agent]`. Published
  results stay open-weight, and the CI check now also scans per-role provenance.
- Every sandbox container gets the host name `zyven-sandbox`.

### Fixed
- **A docstring of only whitespace no longer crashes the repository summary** (found on sympy).
- **Upstream tests that need a missing package no longer stop the gate when named explicitly.** pytest's `--ignore`
  does not apply to a file passed on the command line, so a chosen test file importing `bs4` stopped the whole run.
  Such files are now left out of the named list.
- **No false alarm for read-only query tools with a `command` parameter.** "Marked read-only but runs commands" now
  needs the tool's name to say it runs or writes something (`run_command`, `write_file`). Firecrawl's library search,
  which takes shell-style commands over a read-only file system, keeps the capability listed but no longer fails.
- **Docker not running is now said in words.** A sandboxed skill served through `zyven mcp` or the hub used to fail
  with "Connection closed" when Docker was stopped, and the agent saw only that. It now says that Docker is not
  installed, not running, or that the sandbox image needs `zyven setup`. `zyven verify --docker` stops early with the
  same message.
- **Policy gate: lookups inside the wrapped library are allowed again.** The `getattr` rule added for 0.2.0 also refused
  `getattr(phonenumbers.PhoneNumberFormat, fmt)`, the usual way to turn "E164" into a constant, so a phone-number skill
  verified earlier no longer passed gate 1. A non-literal name is allowed when the object is a name inside a source
  package (`pkg.Thing`, or `Thing` from `from pkg import Thing`), never the module itself or a local value.
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
