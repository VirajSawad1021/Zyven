# AI Usage Disclosure & Programmatic Consumption

Zyven is designed for transparent, controlled, and verifiable AI usage. In compliance with open challenge guidelines, **only open-weight models** are utilized across all roles. Proprietary, closed-source models (such as GPT-4, Claude, or Gemini) are not used for any published result. Some local development experiments did use a proprietary model; those runs are flagged in their provenance (see section 3) and excluded from the results in the README.

This document details every file and function in the repository where artificial intelligence model output is programmatically generated and consumed.

---

## 1. Summary of AI Roles & Model Calls

| File | Function | AI Role | Output Schema | Purpose | Programmatic Handling / Safeguards |
|---|---|---|---|---|---|
| `zyven/ai/roles.py` | `scout` | Scout | `ScoutResult` | Analyzes repository AST digest to identify candidate capabilities. | Validated against Pydantic schema; entry points resolved via `RefResolver` against AST symbol table. |
| `zyven/ai/roles.py` | `architect` | Architect | `CapabilitySpec` | Designs the tool signatures, parameters, and return fields for a capability. | Filtered by deterministic `lint_interface`; parameter names sanitized with `_snake()`; symbols resolved against AST. |
| `zyven/ai/roles.py` | `compiler` | Compiler | `AdapterCode` | Generates Python tool bodies wrapping library functions into an MCP server. | Code parsed into AST and checked by `check_adapter` static policy before sandbox execution. |
| `zyven/ai/roles.py` | `tester` | Tester | `DiffTests` | Generates independent differential test cases calling the library directly. | Validated against tool parameter signatures; inputs tied to expressions; re-queries if tools are omitted. Never sees adapter code. |
| `zyven/ai/roles.py` | `repair` | Repair | `AdapterCode` | Generates corrected tool bodies for tools that failed sandbox verification gates. | Bounded repair loop (max 2 rounds); only failing tools recompiled; re-tested in sandbox. |
| `zyven/agent/gap.py` | `gap_check` | Gap Detector | `GapCheck` | Determines if agent's current tools suffice for a task or if new tools are needed. | Cross-checked for consistency; falls back to missing capabilities if contradictory. |
| `zyven/agent/gap.py` | `match_capability` | Capability Matcher | `CapabilityMatch` | Matches a missing capability to an option in the Skill Library or Catalog. | Model choice strictly checked against valid candidate IDs (`o.id`); invented IDs are dropped. |
| `zyven/compiler/verify.py` | `_differential_gate` | Tester output consumed | `DiffTests` | Each Tester case carries a short reference program that calls the library directly. It is policy-checked, then run in the sandbox and its value is compared with the tool's output. | Every line passes `check_adapter` (the same static policy as adapter code); rejected cases are reported with the reason; the program runs in the container with no network (`zyven/sandbox/diff_check.py::evaluate`). |
| `zyven/agent/self_extend.py` | `run_self_extending` | Gap and match output consumed | `GapCheck`, `CapabilityMatch` | Decides whether to search the skill library and the catalog, and which entry to offer for approval. | The gap check sees only verified tools (`verified_tools` drops tools that run the agent's own code); a match must name a real candidate id; nothing is compiled without a human approval. |
| `zyven/agent/loop.py` | `run_agent` | Tool-Using Agent | OpenAI Chat Completion (Text & Tool Calls) | Iteratively solves user tasks by invoking MCP tools. | Tool calls dispatched to `ToolBox` via MCP JSON-RPC; tool results formatted back into chat context; capped by step limits. |

---

## 2. Detailed Programmatic Consumption by Module

### 2.1 `zyven/ai/roles.py`

#### `scout(provider: ModelProvider, a: Analysis) -> RoleOutcome[ScoutResult]`
- **Model Consumption:** Consumes an AST-based module digest (`repo_digest`) and outputs structured candidate capabilities (`ScoutResult`).
- **Post-Processing & Validation:**
  - Validated using Pydantic `ScoutResult.model_validate_json`.
  - Every proposed entry point is checked by `RefResolver(a).resolve_all()`. Hallucinated or non-existent symbols are stripped out.
  - Returned in a `RoleOutcome` containing dropped/resolved counts.

#### `architect(provider: ModelProvider, a: Analysis, candidate: CandidateCapability) -> RoleOutcome[CapabilitySpec]`
- **Model Consumption:** Takes candidate information and static evidence to produce a formal capability specification (`CapabilitySpec`).
- **Post-Processing & Validation:**
  - Evaluated by `lint_interface(spec, analysis)`: deterministic rules ensuring tools accept natural single-string inputs rather than fragmented components, provide formatted string answers, and return at least one related fact the library computes directly from the same input (found from the static analysis: accessors on the value's class, or sibling functions on the same subject). Any warning triggers one revision request; the revision is kept only if it has fewer warnings.
  - Parameter names are forced to valid Python snake_case identifiers using keyword filtering.
  - Exported symbols and test suites are cross-checked against actual test evidence in `a.tests`.

#### `compiler(provider: ModelProvider, a: Analysis, spec: CapabilitySpec) -> AdapterCode`
- **Model Consumption:** Proposes raw Python tool function bodies (`AdapterCode`).
- **Post-Processing & Validation:**
  - Verified to contain entries for all required tools in `spec.tools`.
  - Fed directly into `assemble()` which applies per-tool import scoping.
  - Subjected to `check_adapter()` AST analysis to verify that no forbidden standard library calls, filesystem writes, or network sockets exist before the code is sent to the Docker sandbox.

#### `tester(provider: ModelProvider, a: Analysis, spec: CapabilitySpec, per_tool: int = 3) -> DiffTests`
- **Model Consumption:** Proposes test cases and Python expressions that compute expected values directly against the library (`DiffTests`).
- **Post-Processing & Validation:**
  - **Adversarial Independence:** The Tester never receives the adapter code written by the Compiler.
  - Test case arguments are filtered to ensure required tool parameters are satisfied.
  - Reference expressions must directly reference input parameters (preventing trivial hardcoded outputs).
  - Automatically re-queries for any tools in the spec that were omitted in the initial response.

#### `repair(provider: ModelProvider, a: Analysis, sub: CapabilitySpec, cur: AdapterCode, failures: dict[str, str], history: list[str]) -> AdapterCode`
- **Model Consumption:** Proposes targeted fixes for specific tool bodies that failed verification gates.
- **Post-Processing & Validation:**
  - Only updates the failing tool subsets.
  - Re-assembled and passed back to the verification gates.

---

### 2.2 `zyven/agent/gap.py`

#### `gap_check(provider: ModelProvider, task: str, tools: list[dict[str, Any]]) -> GapCheck`
- **Model Consumption:** Inspects available MCP tool definitions and decides whether the task requires external tools.
- **Post-Processing & Validation:**
  - Programmatically validates consistency: if `missing_capabilities` is populated, `can_complete_with_current_tools` is forced to `False`.

#### `match_capability(provider: ModelProvider, need: MissingCapability, options: list[Option]) -> CapabilityMatch`
- **Model Consumption:** Evaluates candidates and returns a matching option ID.
- **Post-Processing & Validation:**
  - Checked against `{o.id for o in options}`. If the model hallucinates an ID, `choice` is set to `None` and `confidence` is downgraded to `"low"`.

---

### 2.3 `zyven/agent/loop.py`

#### `run_agent(provider: ModelProvider, task: str, tools: ToolBox, system: str | None, max_steps: int, max_tokens: int | None) -> AgentResult`
- **Model Consumption:** Runs an iterative conversation loop consuming chat responses and tool call requests.
- **Post-Processing & Validation:**
  - Tool calls requested by the model are parsed from OpenAI tool format and dispatched to active MCP servers via `ToolBox.call()`.
  - Tool outputs are appended as tool messages.
  - If any capability the task needs has no verified tool (its compile failed verification, or its approval was rejected), a notice naming each one is added to the system prompt, forbidding the model from claiming or implying library backing for those parts, and the card ends `UNVERIFIED` instead of `DONE`.

---

### 2.4 Where Tester and gap output are executed

- `zyven/compiler/verify.py::_differential_gate` takes each `DiffCase.reference_expr` (a short Python program written by the
  Tester model). Every line is parsed with `ast`, the last line must be an expression, and the whole program passes
  `check_adapter` before it is written to `diff_tests.json`. It is then evaluated inside the sandbox by
  `zyven/sandbox/diff_check.py::evaluate`, and the result is compared with what the compiled tool returns.
- `zyven/agent/self_extend.py::run_self_extending` consumes the `GapCheck` and `CapabilityMatch` results to decide the
  next step of the task. Both are validated structures; an invented capability id is dropped, and a compile only starts
  after a person approves it.

## 3. Open-Weight Model Policy

All AI operations in Zyven are built around open-weight models. The default model configuration uses **Gemma 4** (`gemma-4-26b-a4b-it`) hosted via Google AI Studio or open inference endpoints (e.g., Groq, OpenRouter, or local Ollama).

The policy is a project rule, not a hard block: `is_proprietary()` in `zyven/ai/provider.py` recognises proprietary model IDs (`gemini`, `gpt-`, `gpt4`, `o1`, `o3`, `o4`, `claude`, `command-r`; Gemma is excepted). When one is configured, the provider logs a warning, and its label, the skill provenance and evaluation reports carry `[PROPRIETARY - experiment only]`, so such runs cannot be mistaken for submission results.

The committed surfaces are also checked mechanically: `scripts/check_open_models.py` scans config, skill provenance and evaluation reports for proprietary model identifiers and exits non-zero on a violation. It runs in CI on every pull request.

---

## 4. Optional Agent Runtimes (not part of any published result)

The Control center can start command-line coding agents. They are **not Zyven model calls**: Zyven sends them a task and
reads their output. Each is off by default and labelled `open_weight: false`, because the model behind it is whatever the
program is signed in to.

| Runtime | Model | Where the task text goes |
|---|---|---|
| Codex | the signed-in account's default (a proprietary OpenAI model unless configured otherwise) | OpenAI, or the provider Codex is configured for |
| OpenCode | the model the user selects; its free hosted models by default | OpenCode's hosted provider |
| Claude Code | Anthropic's models | Anthropic |
| Antigravity | whatever `agy models` lists for the account (Claude and gpt-oss models on the development machine) | Antigravity's service, which Google operates |

- `is_proprietary()` and `scripts/check_open_models.py` (section 3) cover Zyven's own model provider, its skill provenance
  and the evaluation reports. They **do not cover these runtimes**, so their output must never be placed in `eval/results/`
  or in a skill's provenance. No README result, skill or evaluation number was produced through them.
- When given Zyven's tools through the hub, an agent can read from and (after approval) write to the services the user has
  connected, such as Notion. The model that decides what to read or write is the agent's, not an open-weight Zyven role.

### Development assistance

Parts of this repository's code, tests and documentation were written with an AI coding assistant (Claude Code, Sonnet 5.5; its
co-authorship is recorded in the commit messages). Live checks with a stronger proprietary model (`gemini-3.5-flash`) were made
only to test the pipeline, were not saved in the repository, and are not used for any result.
