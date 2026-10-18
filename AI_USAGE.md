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
| `zyven/agent/gap.py` | `gap_check` | Gap Detector | `GapResult` | Determines if agent's current tools suffice for a task or if new tools are needed. | Cross-checked for consistency; falls back to missing capabilities if contradictory. |
| `zyven/agent/gap.py` | `match_capability` | Capability Matcher | `CapabilityMatch` | Matches a missing capability to an option in the Skill Library or Catalog. | Model choice strictly checked against valid candidate IDs (`o.id`); invented IDs are dropped. |
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
  - Evaluated by `lint_interface(spec)`: deterministic rules ensuring tools accept natural single-string inputs rather than fragmented components and provide formatted string answers.
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

#### `gap_check(provider: ModelProvider, task: str, tools: list[dict[str, Any]]) -> GapResult`
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

## 3. Open-Weight Model Policy

All AI operations in Zyven are built around open-weight models. The default model configuration uses **Gemma 4** (`gemma-4-26b-a4b-it`) hosted via Google AI Studio or open inference endpoints (e.g., Groq, OpenRouter, or local Ollama).

The policy is a project rule, not a hard block: `is_proprietary()` in `zyven/ai/provider.py` recognises proprietary model IDs (`gemini`, `gpt-`, `gpt4`, `o1`, `o3`, `o4`, `claude`, `command-r`; Gemma is excepted). When one is configured, the provider logs a warning, and its label, the skill provenance and evaluation reports carry `[PROPRIETARY - experiment only]`, so such runs cannot be mistaken for submission results.
