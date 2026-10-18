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
   - Wrapping the library code into an adapter does not break the upstream repository's own test suite. All relevant upstream test files pass inside the container.

4. **Input Robustness (Gate 4):**
   - Each tool handles input variations gracefully without unhandled exceptions or crashes. Inputs with leading/trailing whitespace, embedded spaces in formatted numbers, and boundary strings either return valid parsed data or raise clean `ValueError` exceptions.

5. **MCP Protocol Conformance (Gate 5):**
   - The assembled script functions as a compliant Model Context Protocol (MCP) server over standard input/output (`stdio`). It responds correctly to `tools/list` and executes sample calls over `tools/call`.

6. **Differential Equivalence on Reference Cases (Gate 6):**
   - For every differential test case generated independently by the Tester role, calling the MCP tool yields the identical JSON-formatted value as calling the underlying source library directly.

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

5. **Sandbox Dependency on Docker:**
   - The multi-gate verification process requires Docker. On systems where Docker is unavailable or inactive, untrusted code cannot be executed in the locked-down container sandbox, and compilation cannot produce verified skills.

---

## 3. Operational & System Boundaries

- **Single Task Concurrency:** To prevent hitting model host rate limits and resource contention during sandbox execution, the task board processes one task compile at a time.
- **Language Support:** Currently targets Python libraries (Python 3.11+). Libraries requiring complex compilation toolchains (e.g., custom Fortran or Rust bindings not pre-installed in the base sandbox image) may fail upstream test gates.
- **No Direct Internet in Sandbox:** The container sandbox runs with `--network none`. Libraries that attempt to make live HTTP/DNS queries during their test suite or validation will fail and be rejected.
