"""Typed contracts for every AI role. Model output is only ever consumed through these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---- Scout: repository digest -> user-level capability candidates ---------------------------


class CandidateCapability(BaseModel):
    name: str = Field(description="snake_case identifier, e.g. nepali_date_conversion")
    title: str = Field(description="short human title")
    description: str = Field(description="what an AI agent could accomplish with this capability")
    entry_points: list[str] = Field(description="fully qualified symbol ids copied exactly from the digest")
    why_agents_need_it: str = Field(description="why a language model cannot reliably do this without a tool")
    risk_notes: list[str] = Field(default_factory=list, description="side effects, heavy deps, or uncertainty")
    tests: list[str] = Field(default_factory=list, description="reviewer-chosen upstream test files to run (repo-relative)")


class ScoutResult(BaseModel):
    capabilities: list[CandidateCapability]


# ---- Architect: one candidate + evidence -> capability spec ---------------------------------

JsonType = Literal["string", "integer", "number", "boolean", "array", "object"]


class ToolParam(BaseModel):
    name: str
    type: JsonType
    description: str
    required: bool = True
    example: str | int | float | bool | None = None


class ReturnField(BaseModel):
    name: str
    type: JsonType
    description: str


class ToolSpec(BaseModel):
    name: str = Field(description="snake_case tool name an agent will call")
    description: str = Field(description="when and why an agent should call this tool")
    params: list[ToolParam]
    returns: list[ReturnField]
    implementation_symbols: list[str] = Field(description="symbol ids from the evidence that implement this tool")
    implementation_notes: str = Field(description="exactly how to call the library: imports, argument conversion")
    example_args: dict[str, str | int | float | bool] = Field(description="a realistic example call")


class ExcludedSymbol(BaseModel):
    symbol: str
    reason: str


class CapabilitySpec(BaseModel):
    name: str
    title: str
    summary: str
    mode: Literal["wrap", "extract"] = "wrap"
    tools: list[ToolSpec]
    included_symbols: list[str]
    excluded_symbols: list[ExcludedSymbol] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list, description="third-party pip packages needed")
    side_effects: list[str] = Field(default_factory=list)
    relevant_tests: list[str] = Field(description="test file paths from the evidence that exercise this capability")
    uncertainties: list[str] = Field(default_factory=list)


# ---- Compiler / Repair: spec -> tool function bodies ------------------------------------------


class ToolImpl(BaseModel):
    tool: str = Field(description="tool name from the spec")
    imports: list[str] = Field(description="full import statements, e.g. 'from nepali.date_converter import converter'")
    body: str = Field(description="Python statements for the function body. Parameters are local variables. "
                                  "Must `return` a dict whose keys are exactly the spec's return field names.")


class AdapterCode(BaseModel):
    tools: list[ToolImpl]


# ---- Tester: spec + library (NOT the adapter) -> differential test cases ---------------------


class DiffCase(BaseModel):
    tool: str = Field(description="tool name from the spec")
    args: dict[str, str | int | float | bool] = Field(description="arguments for the tool call")
    field: str = Field(description="one return field of the tool to check")
    reference_imports: list[str] = Field(description="import statements for the reference expression")
    reference_expr: str = Field(description="a short Python program that calls the library directly: optional setup "
                                            "statements on separate lines, then a LAST line that is one expression "
                                            "evaluating to the value the tool must return in `field` (same JSON type/format). "
                                            "Refer to the case's arguments as {arg_name} placeholders, e.g. "
                                            "stdnum.luhn.checksum({number})")


class DiffTests(BaseModel):
    cases: list[DiffCase]
