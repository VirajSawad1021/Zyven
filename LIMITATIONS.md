# Scope, Guarantees, and Limitations

This document provides an honest appraisal of Zyven's scope, detailing exactly what its verification gates prove, what they do not prove, and the system's operational boundaries.

---

## 1. What Verification Proves

When a compiled skill receives a passing validation report and is marked as verified by Zyven, the following guarantees have been empirically observed in a locked-down container sandbox:

1. **Static Policy Conformance (Gate 1):**
   - The generated MCP adapter code contains no forbidden standard library imports (`os`, `sys`, `subprocess`, `socket`, `shutil`, `urllib`).
   - The code contains no calls to dangerous builtins (`__import__`, `eval`, `exec`, `open`).
   - All imports are strictly scoped per-tool to prevent module shadowing.

2. **Clean Import Isolation (Gate 2):**
   - The assembled MCP server script (`server.py`) can be imported cleanly inside an isolated container with only its declared pinned dependencies present on `PYTHONPATH`.

3. **Upstream Regression Safety (Gate 3):**
   - The upstream repository's own tests that exercise the wrapped code pass inside the container. Test files that import packages not installed in the sandbox (e.g. `bs4`) are skipped, and the skip and its reason are recorded rather than counted as passes. One failing upstream test fails the gate, even if it is unrelated to the wrapped functions (this kept sympy from verifying).

4. **Input Robustness (Gate 4):**
   - Equivalent spellings of an example input (extra or missing whitespace, separators, letter case) give the same result as the example call, without crashing. Gate 5 separately checks that clearly invalid input is rejected with an error rather than a wrong answer.

5. **MCP Protocol Conformance (Gate 5):**
   - The assembled script functions as a compliant Model Context Protocol (MCP) server over standard input/output (`stdio`). It responds correctly to `tools/list` and executes sample calls over `tools/call`.

6. **Differential Equivalence on Reference Cases (Gate 6):**
   - For every differential test case generated independently by the Tester role, calling the MCP tool yields the identical JSON-formatted value as calling the underlying source library directly. A tool with no usable test case cannot pass this gate.

---

## 2. What Verification Does NOT Prove

Users and evaluators should be aware of what Zyven's verification process does not guarantee:

1. **Not Full Formal Equivalence Over Infinite Domains:**
   - Differential testing is an empirical verification method over a representative sample space. It does not constitute a mathematical proof of correctness for all possible arbitrary inputs.
   
2. **Upstream Library Bugs are Inherited:**
   - If the upstream open-source library contains bugs, incorrect algorithms, or outdated validation rules, Zyven's differential gate will match the library's behavior. Verification guarantees that the tool faithfully exposes what the library computes, not that the library itself is infallible.

3. **Pure Functionality vs Stateful Workflows:**
   - Zyven is designed for deterministic, functional, or algorithmic libraries (checksums, calendars, number formatting, math). It is not designed to compile servers around stateful databases, persistent background daemons, or services requiring external network infrastructure.

4. **Out-of-Distribution Inputs:**
   - While Gate 4 tests fuzzing variations, inputs vastly outside the expected parameter domains may still produce unexpected behavior or unhandled exceptions from deep within the underlying library.

5. **The Reference Is Model-Written Too:**
   - The Tester's reference expressions are written by a model. It never sees the adapter, but if the Tester and the Compiler make the same mistake (for example both call the wrong library function), a wrong tool can pass. A wrong reference can also make a correct tool fail; the gate then reports the mismatch and the tool is repaired or dropped, never shipped.

6. **The Answer Text Is Still the Model's:**
   - Verification covers tool outputs. The agent's final answer is written by the model from those outputs, and it can still misreport them. Deciding whether a task needs a tool at all (the gap check) and which skill or repository fits (matching) are model judgements too, so a task can be answered without any tool when the model believes it knows the answer.

7. **Sandbox Dependency on Docker:**
   - The multi-gate verification process requires Docker. On systems where Docker is unavailable or inactive, untrusted code cannot be executed in the locked-down container sandbox, and compilation cannot produce verified skills.

---

## 3. Operational & System Boundaries

- **Single Task Concurrency:** To prevent hitting model host rate limits and resource contention during sandbox execution, the task board processes one task compile at a time.
- **Language Support:** Currently targets Python libraries (Python 3.11+). Libraries requiring complex compilation toolchains (e.g., custom Fortran or Rust bindings not pre-installed in the base sandbox image) may fail upstream test gates.
- **Skills Run Sandboxed at Runtime:** When the agent uses a verified skill, its MCP server runs in the same locked-down container as verification, so using skills also requires Docker, and each skill adds about 1–2 s of container start-up per task. The `ZYVEN_SKILL_RUNTIME=host` opt-in removes that isolation and is meant for development only.
- **Gap Detection Is a Model Judgement:** Whether the agent decides it needs a verified tool, and so goes to the catalog, is the model's call, and a small model is not consistent. On the same graph question it sometimes says the task can be done with the tools it has. Tightening the prompt made it over-flag easy tasks such as `17 * 23`, so we left it. The reliable route is to compile with the CLI first (`zyven compile ...`; the Explorer page only analyzes a repository and has no compile button) and put the skill in the board's library, so the agent reuses it. Tools that run the agent's own code are not counted when judging whether a gap exists.
- **Connections Share the Model's Prompt:** Every tool of every switched-on connection is described to the model on each call. Notion alone adds 65 tools, which can exhaust a small free quota. Keep connections off for tasks that do not need them. A connection that does not answer within 30 s is skipped.
- **No Direct Internet in Sandbox:** The container sandbox runs with `--network none`. Libraries that attempt to make live HTTP/DNS queries during their test suite or validation will fail and be rejected.

---

## 4. Control Center, Connections and Coding Agents (optional extras)

These features are separate from the verification pipeline above. **Zyven's six gates verify skills compiled from
repositories. They say nothing about coding agents. For third-party MCP servers, `zyven verify` does narrower,
outside-in checks (section 6), which are not the same as the six gates.**

- **Connected services are trusted as far as the user chose to trust them.** Whether a tool is read-only comes from the
  server's own hint. A server that marks a destructive tool read-only would run without an approval card. An unknown hint
  means ask, but a wrong hint is not detected.
- **Pinned definitions protect against a changed description, not against changed behaviour.** Each Test records a hash of
  every tool definition, and a later change is refused. A server can still do something different behind the same
  definition. Connections tested before this feature have no pins, so they load as before until they are tested again.
- **Tool output is untrusted text.** A page or message returned by a connected service can try to steer the model
  (prompt injection). The approval card on writes, which shows the exact arguments, is the safeguard; reads are not gated.
- **Each coding agent's containment is that program's own.** Zyven checked it on Windows and configured it (Codex's sandbox with temp
  folders and network closed and without loading the user's plugins; OpenCode's permission file; Claude Code's tool
  allowlist; the Qoder CLI's restricted built-in tools), but relies on those programs enforcing it. The Qoder runtime was run
  live with a Qwen model whose host and exact weights Zyven cannot verify. Claude Code's was not checked live, and Antigravity's headless mode
  does not work on the development machine. macOS and Linux were not tried for the agents.
- **Full PC access removes the sandbox on request.** A wrong or manipulated model can then read, change and delete anything the
  user's account can. It is off unless the machine owner sets `ZYVEN_ALLOW_FULL_ACCESS=1`, and each task needs a confirmation.
- **The board has no login.** The guard refuses a foreign `Host` and cross-site writes, which stops the usual browser-based
  routes. It does not stop another program running as the same user from calling the API.
- **Secrets are stored in plain files** in the board directory (connection keys, OAuth tokens). On Windows the file mode
  is not a protection. Use a board directory only you can read; an OS secret store would be better.
- **The hub token and the OpenCode / Claude Code config files sit in the task folder**, readable by that run's agent. They are
  valid for that run only.
- **Coding agents send the task text to their provider** (for example OpenAI for Codex), unlike the open-weight roles above.
- **Notion rotates refresh tokens**, so copying a connection's secrets to another process invalidates the original
  sign-in. One board should own a connection.
- **Hub start-up time:** the first request in a run starts that run's tool servers, in parallel; each Docker-based skill adds
  1-2 s. One real skill (IBAN validation) was served through the hub with Codex; a task with many skills has not been timed.

---

## 5. What the Evaluation Does and Does Not Show

- **The baseline is the model alone, not the model with a Python interpreter.** A model that can write and run code can often
  compute a checksum or a graph algorithm itself (in rehearsals, a 26B model with a command sandbox answered some of the
  networkx questions without any skill). The result is therefore best read as "a small model without code execution, with and
  without a verified tool", not as "models cannot do this". A model-plus-interpreter baseline is an open issue (#24).
- **Small samples, not held out.** Each suite is 18 to 40 questions on a library the pipeline was developed against. The numbers
  are a direction, not a benchmark. A held-out suite across many libraries is an open issue (#25).
- **Output caps decide a lot.** At a 4096-token cap, 23 of 24 questions without the skill ended with the budget spent and no answer,
  and the misses with the skill were the same cap. At 8192 both sides improve (3/12 vs 11/12 on a smaller sample).
- **The compile-then-reuse timing (2 minutes, then 19 seconds) is one illustrative run.** The learning-curve evaluation is an open
  issue (#8); the Insights page title is not a claim that it was done.
- **Qoder results are development checks only** (a 5-question run), not part of any published number.
- **Verification is narrow** (sections 1 and 2). A verified tool matches the library on sampled cases; it does not make the library
  correct.

---

## 6. `zyven verify`, `zyven mcp` and Agents as Compile Roles

- **`zyven verify` is not a security audit.**
  - **It never reads the server's code.** It checks what the server *says* (names, schemas, descriptions, annotations) and,
    with `--probe`, how it treats input its own schema forbids. A server whose tools do harm *with valid input* passes.
  - **The poisoning scan is a list of known patterns.** A carefully written malicious description can avoid all of them.
    Ordinary descriptions were checked for false positives ("send a message", "read a file"), but the list will need tuning.
  - **The stability check only sees changes between two connections a few seconds apart, or against your lock file.** A
    server that changes its definitions after a week, or only for some clients, is caught only by a later run against the
    lock file.
  - **A PASS on the host still ran the server with your permissions.** Use `--docker` for code you do not trust. Servers
    that must reach their service to start need `--allow-network`, and the report says so.
- **The community scan in the README is a snapshot** (one day, one version per package, dummy keys, mostly no network). Some
  servers behave differently when they are signed in.
- **`zyven mcp` with `--connections` has no approval cards.** Write tools are then guarded only by the agent's own permission
  prompt. Codex was tested live with `zyven mcp`, and Claude Code was not.
- **Agents as compile roles:**
  - **The code and prompts go to the agent's provider.**
  - **Zyven cannot tell which model the agent used.** This is why the open-model check refuses committed skills with a
    `[coding agent]` role.
  - **Live runs so far:**
    - Codex compiled and verified one capability (packaging `version_specifiers`, 6/6 gates, first attempt).
    - Qoder answered a structured question.
    - OpenCode hit its free-usage limit.
    - Antigravity hung in this environment.
    - Claude Code was not run.
  - One verified compile is an example, not a comparison between agents.
- **`zyven reassemble` trusts the saved differential cases.** It reruns the six gates with the cases the Tester wrote when the
  skill was first compiled. It does not write new ones. A weak original test set stays weak.
- **The network allowlist works through a proxy.**
  - **Programs that ignore `HTTPS_PROXY` cannot reach anything.** Node's built-in `fetch` is one of them, unless told to
    use the proxy. That fails closed: safe, but such a server may not work with an allowlist.
  - **The check is on host names.** The proxy resolves the names and refuses IP literals. Only ports 443 and 80 are
    allowed.
  - **TLS is not inspected,** so what is sent to an allowed host is not seen.
  - **It applies to `zyven verify --docker` so far,** not yet to compiled skills at run time.
- **`zyven export` copies the evidence; it does not re-verify.** The exported Docker image installs the library from git
  at the verified commit. If that commit or repository disappears upstream, the image cannot be rebuilt.
- **`zyven outdated` maps symbols to files by module path.** A symbol re-exported from another module, or code moved
  between files, can be missed or over-reported. "Touched" means the file changed, not that the behaviour the skill uses
  changed.
- **The mutation score measures the Tester's cases as much as the gates.** The differential gate can only catch what a
  case looks at. Equivalent mutants are classified by hand. Each score is one run with one seed; model-written cases
  vary between runs.
- **Calibration removes wrong cases, which can also hide real bugs.** A case that fails on the unmutated skill is assumed
  to have a wrong expected value. Each dropped case is listed so it can be checked: every one dropped so far was a wrong
  expectation, not a bug in the skill.
- **Installed copies:**
  - **Only Windows was tested by hand**, in a clean `uvx` room. Linux is covered by the CI package job, and macOS was not tried.
  - **A git install has no dashboard build.** The board then serves its single-file page. Wheels built by the release
    workflow include the dashboard.
