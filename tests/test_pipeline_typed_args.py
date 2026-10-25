"""Tools that take lists or objects, and reference programs that build an object first (found compiling networkx)."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.ai.schemas import CapabilitySpec, DiffCase, DiffTests, ReturnField, ToolParam, ToolSpec  # noqa: E402
from zyven.compiler import verify as V  # noqa: E402
from zyven.sandbox import diff_check  # noqa: E402


def _tool(name="triangle_count", **ptypes) -> ToolSpec:
    ptypes = ptypes or {"edge_list": "array"}
    return ToolSpec(name=name, description="d", params=[ToolParam(name=k, type=t, description="x") for k, t in ptypes.items()],
                    returns=[ReturnField(name="total", type="integer", description="count")], implementation_symbols=[],
                    implementation_notes="n", example_args={"edge_list": '[["A","B"],["B","C"],["A","C"]]'})


def _spec(*tools) -> CapabilitySpec:
    return CapabilitySpec(name="graphs", title="Graphs", summary="s", tools=list(tools), included_symbols=[], excluded_symbols=[],
                          relevant_tests=[], side_effects=[], uncertainties=[], mode="wrap")


# --- typed example arguments ---------------------------------------------------------------------------------------

def test_list_and_object_examples_written_as_text_become_real_lists_and_objects():
    params = [ToolParam(name="edges", type="array", description=""), ToolParam(name="opts", type="object", description=""),
              ToolParam(name="n", type="integer", description=""), ToolParam(name="w", type="number", description=""),
              ToolParam(name="flag", type="boolean", description=""), ToolParam(name="label", type="string", description="")]
    out = V.typed_args(params, {"edges": '[["A", "B"], ["B", "C"]], ', "opts": "{'k': 1}", "n": " 7 ", "w": "2.5",
                                "flag": "True", "label": "  keep as text  "})
    assert out == {"edges": [["A", "B"], ["B", "C"]], "opts": {"k": 1}, "n": 7, "w": 2.5, "flag": True, "label": "  keep as text  "}


def test_a_value_that_cannot_be_converted_is_left_alone_and_unknown_names_pass_through():
    params = [ToolParam(name="edges", type="array", description=""), ToolParam(name="opts", type="object", description="")]
    out = V.typed_args(params, {"edges": "not a list at all", "opts": "[1, 2]", "extra": "x", "num": 3})
    assert out == {"edges": "not a list at all", "opts": "[1, 2]", "extra": "x", "num": 3}  # a list where an object is wanted


def test_the_smoke_plan_sends_lists_as_lists_and_only_varies_plain_text():
    plan = V.smoke_plan(_spec(_tool(edge_list="array", mode="string")))["tools"]["triangle_count"]
    assert plan["args"]["edge_list"] == [["A", "B"], ["B", "C"], ["A", "C"]]
    assert all(isinstance(v["edge_list"], list) for v in plan["variants"])  # the list is never turned into padded text


# --- reference programs -------------------------------------------------------------------------------------------

SERVER = textwrap.dedent('''
    import itertools

    def triangle_count(edge_list):
        edges = {frozenset(e) for e in edge_list}
        nodes = sorted({n for e in edges for n in e})
        total = sum(1 for a, b, c in itertools.combinations(nodes, 3)
                    if {frozenset((a, b)), frozenset((b, c)), frozenset((a, c))} <= edges)
        return {"total": total}
''')


def _gate(tmp_path, monkeypatch, cases):
    (tmp_path / "server.py").write_text(SERVER, encoding="utf-8")

    def fake_run(cmd, mounts, policy, workdir="/src"):  # run diff_check here instead of in a container
        out = diff_check.main(str(tmp_path / "server.py"), str(tmp_path / "diff_tests.json"))
        return SimpleNamespace(stdout="ZYVEN_DIFF_REPORT=" + json.dumps(out), stderr="")

    monkeypatch.setattr(V, "run", fake_run)
    failing: dict = {}
    gate = V._differential_gate(tmp_path, _spec(_tool()), DiffTests(cases=cases), {}, None, {"networkx"}, failing)
    return gate, json.loads((tmp_path / "diff_tests.json").read_text(encoding="utf-8"))


def _case(expr, imports=("import networkx as nx",), args=None):
    return DiffCase(tool="triangle_count", args=args or {"edge_list": '[["A","B"],["B","C"],["A","C"],["C","D"]]'}, field="total",
                    reference_imports=list(imports), reference_expr=expr)


def test_a_reference_that_builds_a_graph_first_is_accepted_and_checked_against_the_library(tmp_path, monkeypatch):
    program = "G = nx.Graph({edge_list})\nsum(nx.triangles(G).values()) // 3"
    gate, saved = _gate(tmp_path, monkeypatch, [_case(program)])
    assert gate.passed, gate.detail
    assert saved["cases"][0]["args"]["edge_list"] == [["A", "B"], ["B", "C"], ["A", "C"], ["C", "D"]]  # a list, not text


def test_a_wrong_tool_output_is_still_caught_when_the_reference_is_a_program(tmp_path, monkeypatch):
    program = "G = nx.Graph({edge_list})\nsum(nx.triangles(G).values()) // 3 + 1"  # the 'library' disagrees with the tool
    gate, _ = _gate(tmp_path, monkeypatch, [_case(program)])
    assert not gate.passed and "first mismatch" in gate.detail


@pytest.mark.parametrize("expr, imports, reason", [
    ("import os; os.listdir('.')", ("import networkx as nx",), "import"),          # statements are allowed, imports are policed
    ("G = nx.Graph()", ("import networkx as nx",), "last line must be"),              # no final expression
    ("nx.Graph(", ("import networkx as nx",), "never closed|invalid|expected"),       # not Python
    ("sum(1 for _ in open('x'))", ("import networkx as nx",), "open"),                # a forbidden builtin
])
def test_unsafe_or_malformed_references_are_rejected_and_the_gate_says_why(tmp_path, monkeypatch, expr, imports, reason):
    gate, saved = _gate(tmp_path, monkeypatch, [_case(expr, imports)])
    assert not gate.passed and saved["cases"] == []
    assert "rejected by policy (e.g. triangle_count:" in gate.detail
    import re
    assert re.search(reason, gate.detail), gate.detail


def test_diff_check_runs_setup_statements_then_the_last_expression_only():
    env: dict = {}
    assert diff_check.evaluate("xs = [1, 2, 3]\nys = [x * 2 for x in xs]\nsum(ys)", env) == 12
    with pytest.raises(ValueError, match="must end with an expression"):
        diff_check.evaluate("x = 1", {})
