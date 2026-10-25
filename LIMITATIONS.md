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
- **No Direct Internet in Sandbox:** The container sandbox runs with `--network none`. Libraries that attempt to make live HTTP/DNS queries during their test suite or validation will fail and be rejected.

---

## 4. Control Center, Connections and Coding Agents (optional extras)

These features are separate from the verification pipeline above. **Zyven's six gates verify skills compiled from
repositories; they say nothing about third-party MCP servers or coding agents.**

- **Connected services are trusted as far as the user chose to trust them.** Whether a tool is read-only comes from the
  server's own hint. A server that marks a destructive tool read-only would run without an approval card. An unknown hint
  means ask, but a wrong hint is not detected.
- **Tool output is untrusted text.** A page or message returned by a connected service can try to steer the model
  (prompt injection). The approval card on writes, which shows the exact arguments, is the safeguard; reads are not gated.
- **Each coding agent's containment is that program's own.** Zyven checked it on Windows and configured it (Codex's sandbox with temp
  folders and network closed and without loading the user's plugins; OpenCode's permission file; Claude Code's tool
  allowlist), but relies on those programs enforcing it. Claude Code's was not checked live, and Antigravity's headless mode
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
