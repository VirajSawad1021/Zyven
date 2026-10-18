"""Offline tests for the capability compiler (no network, no API key, no Docker).

A tiny synthetic repository is generated per test session so the analyzer, reference resolution, policy,
server assembly and harness-side cleanup are checked against known ground truth.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.ai import provider as prov  # noqa: E402
from zyven.ai.provider import ModelProvider  # noqa: E402
from zyven.ai.roles import _snake, lint_interface
from zyven.ai.roles import tester as run_tester  # name must not start with "test" (pytest collection)
from zyven.ai.schemas import AdapterCode, CapabilitySpec, ReturnField, ToolImpl, ToolParam, ToolSpec  # noqa: E402
from zyven.analysis.analyzer import analyze  # noqa: E402
from zyven.analysis.miner import baseline_candidates, repo_digest  # noqa: E402
from zyven.analysis.refs import RefResolver  # noqa: E402
from zyven.compiler.build import assemble  # noqa: E402
from zyven.compiler.policy import check_adapter  # noqa: E402
from zyven.compiler.verify import input_variants  # noqa: E402

FILES = {
    "LICENSE": "MIT License\n\nPermission is hereby granted, free of charge, to any person...\n",
    "calc/__init__.py": "from ._core import checksum, is_valid\n",
    "calc/_core.py": '''
        """Checksums."""
        import os


        class Converter:
            def convert(self, value):
                """Convert a value."""
                return _helper(value)


        def _helper(v):
            return v * 2


        converter = Converter()


        def checksum(number: str) -> int:
            """Compute a checksum.

            >>> checksum("12")
            3
            """
            return sum(int(c) for c in number)


        def is_valid(number: str) -> bool:
            """Check a number."""
            return checksum(number) % 10 == 0


        def read_config():
            return os.environ.get("X")
    ''',
    "tests/test_core.py": '''
        from calc import checksum
        from calc._core import converter


        def test_checksum():
            assert checksum("12") == 3


        def test_convert():
            assert converter.convert(2) == 4
    ''',
    "tests/test_more.doctest": ">>> from calc import is_valid\n>>> is_valid('19')\nTrue\n",
}
for i in range(5):  # a family of modules sharing one API, for digest folding
    FILES[f"calc/fam/m{i}.py"] = f'''
        """Family member {i}."""


        def compact(number):
            return number


        def validate(number):
            return number


        def is_valid(number):
            return True
    '''


@pytest.fixture(scope="session")
def repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("synthetic")
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    (root / "calc/fam/__init__.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def analysis(repo):
    return analyze(repo)


def sym(a, sid):
    return next(s for s in a.symbols if s.id == sid)


# ---- analyzer ---------------------------------------------------------------------------------

def test_license_packages_and_exports(analysis):
    assert analysis.license == "MIT"
    assert analysis.packages == ["calc"]
    assert "calc.checksum" in sym(analysis, "calc._core.checksum").exported_as


def test_calls_resolve_through_module_instances(analysis):
    assert "calc._core._helper" in sym(analysis, "calc._core.Converter.convert").calls
    assert "calc._core.checksum" in sym(analysis, "calc._core.is_valid").calls


def test_side_effects_detected(analysis):
    assert "environment" in sym(analysis, "calc._core.read_config").side_effects
    assert sym(analysis, "calc._core.checksum").side_effects == []


def test_test_links_python_doctest_file_and_docstring(analysis):
    assert "tests/test_core.py" in sym(analysis, "calc._core.checksum").tested_by
    assert "tests/test_more.doctest" in sym(analysis, "calc._core.is_valid").tested_by
    kinds = {t.kind for t in analysis.tests}
    assert {"python", "doctest-file", "module-doctest"} <= kinds


# ---- references -------------------------------------------------------------------------------

@pytest.mark.parametrize("ref,expected", [
    ("calc._core.checksum", "calc._core.checksum"),
    ("calc.checksum", "calc._core.checksum"),  # public re-export
    ("calc._core.converter.convert", "calc._core.Converter.convert"),  # through module instance
    ("calc._core.convert", "calc._core.Converter.convert"),  # module.method with a single instance
    ("calc.made_up", None),  # invented
    ("convert", None),  # ambiguous bare name
])
def test_reference_resolution(analysis, ref, expected):
    assert RefResolver(analysis).resolve(ref) == expected


# ---- digest + baseline ------------------------------------------------------------------------

def test_digest_folds_module_families(analysis):
    d = repo_digest(analysis)
    assert "5 modules share a common API" in d
    assert "## module calc.fam.m0" not in d  # folded, not listed in detail
    assert "calc._core.checksum" in d


def test_baseline_candidates_are_deterministic(analysis):
    a, b = baseline_candidates(analysis), baseline_candidates(analysis)
    assert [c.entry_points for c in a] == [c.entry_points for c in b]


# ---- policy -----------------------------------------------------------------------------------

@pytest.mark.parametrize("code,ok", [
    ("from calc import checksum\nx = checksum('1')", True),
    ("import json, datetime\nx = json.dumps({})", True),
    ("import os\nos.system('ls')", False),
    ("x = eval('1+1')", False),
    ("x = locals()", False),
    ("x = ().__class__.__bases__", False),
    ("from . import y", False),
    ("def f(:\n", False),
])
def test_static_policy(code, ok):
    assert check_adapter(code, {"calc"}).ok is ok


# ---- server assembly --------------------------------------------------------------------------

def _spec(*tools):
    return CapabilitySpec(name="calc_tools", title="Calc", summary="s", tools=list(tools), included_symbols=[],
                          relevant_tests=[])


def _tool(name, params=("number",)):
    return ToolSpec(name=name, description="d", params=[ToolParam(name=p, type="string", description="x") for p in params],
                    returns=[ReturnField(name="value", type="integer", description="v")],
                    implementation_symbols=[], implementation_notes="", example_args={params[0]: "12"})


def test_assembly_scopes_imports_per_tool(repo):
    # Two tools importing different functions under the same name must not shadow each other.
    spec = _spec(_tool("first"), _tool("second"))
    code = AdapterCode(tools=[
        ToolImpl(tool="first", imports=["from calc._core import checksum as f"], body="return {'value': f(number)}"),
        ToolImpl(tool="second", imports=["from calc.fam.m0 import compact as f"], body="return {'value': len(f(number))}"),
    ])
    src = assemble(spec, code, {})
    ast.parse(src)
    stub = "class _S:\n    def tool(self, **k):\n        return lambda fn: fn\n"
    src = src.replace("from mcp.server.mcpserver import MCPServer", stub).replace("MCPServer(", "_S(); _unused = dict(")
    sys.path.insert(0, str(repo))
    ns: dict = {}
    exec(compile(src, "server", "exec"), ns)  # noqa: S102 - our own assembled code, synthetic repo
    assert ns["first"]("12") == {"value": 3}
    assert ns["second"]("12") == {"value": 2}


def test_missing_implementation_becomes_not_implemented():
    src = assemble(_spec(_tool("only")), AdapterCode(tools=[]), {})
    assert "NotImplementedError" in src and ast.parse(src)


# ---- harness-side checks on model output ------------------------------------------------------

def test_input_variants():
    assert {"number": "4992 7398 71"} in input_variants({"number": "4992739871"})
    assert input_variants({"date": "2082-06-15"}) == [{"date": "  2082-06-15 "}]  # separators keep meaning


def test_interface_lint():
    split = _tool("convert", params=("year", "month", "day"))
    assert any("components of one value" in w for w in lint_interface(_spec(split)))
    good = _tool("convert")
    good.returns = [ReturnField(name="date", type="string", description="YYYY-MM-DD")]
    assert lint_interface(_spec(good)) == []


def test_snake_case_names():
    assert _snake("IbanNumber") == "iban_number"
    assert _snake("2x") == "tool_2x"


def test_tester_cases_are_filtered_by_harness(analysis, monkeypatch):
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    cases = {"cases": [
        {"tool": "first", "args": {"number": "12"}, "field": "value",
         "reference_imports": ["calc._core"], "reference_expr": "calc._core.checksum({number})"},   # kept, import fixed
        {"tool": "first", "args": {"number": "12", "bogus": 1}, "field": "value",
         "reference_imports": [], "reference_expr": "1"},                                         # unknown param
        {"tool": "first", "args": {"number": "12"}, "field": "nope",
         "reference_imports": [], "reference_expr": "1"},                                         # unknown field
        {"tool": "first", "args": {"number": "12"}, "field": "value",
         "reference_imports": [], "reference_expr": "calc._core.checksum('99')"},                 # not tied to input
    ]}
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    body = {"choices": [{"message": {"role": "assistant", "content": json.dumps(cases)}, "finish_reason": "stop"}]}
    p._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    out = run_tester(p, analysis, _spec(_tool("first")))
    assert len(out.cases) == 1
    assert out.cases[0].reference_imports == ["import calc._core"]


def test_tester_requeries_missing_tools(analysis, monkeypatch):
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    spec = _spec(_tool("first"), _tool("second"))
    cases_1 = {"cases": [
        {"tool": "first", "args": {"number": "12"}, "field": "value",
         "reference_imports": ["calc._core"], "reference_expr": "calc._core.checksum({number})"}
    ]}
    cases_2 = {"cases": [
        {"tool": "second", "args": {"number": "34"}, "field": "value",
         "reference_imports": ["calc._core"], "reference_expr": "calc._core.checksum({number})"}
    ]}
    responses = [cases_1, cases_2]
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    p._client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": json.dumps(responses.pop(0))}, "finish_reason": "stop"}]})
    ))
    out = run_tester(p, analysis, spec)
    assert len(out.cases) == 2
    assert {c.tool for c in out.cases} == {"first", "second"}


# ---- src-style layouts and tests needing third-party packages ---------------------------------

def test_source_root_detection_and_module_names(tmp_path):
    (tmp_path / "src/cal").mkdir(parents=True)
    (tmp_path / "src/cal/__init__.py").write_text("from .core import convert\n", encoding="utf-8")
    (tmp_path / "src/cal/core.py").write_text("def convert(d):\n    return d\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests/test_core.py").write_text(
        "from cal import convert\n\ndef test_convert():\n    assert convert(1) == 1\n", encoding="utf-8")
    (tmp_path / "tests/test_web.py").write_text(
        "from bs4 import BeautifulSoup\nfrom cal import convert\n\ndef test_web():\n    pass\n", encoding="utf-8")
    (tmp_path / "license.txt").write_text("The MIT License (MIT)\n", encoding="utf-8")
    a = analyze(tmp_path)
    assert a.source_root == "src" and a.packages == ["cal"] and a.license == "MIT"
    assert "cal.core.convert" in {s.id for s in a.symbols}  # named from the source root, not "src.cal..."
    assert "tests/test_core.py" in sym(a, "cal.core.convert").tested_by
    needs = {t.file: t.third_party for t in a.tests}
    assert needs["tests/test_web.py"] == ["bs4"] and needs["tests/test_core.py"] == []


def test_tester_imports_naming_a_class_are_repaired(analysis, monkeypatch):
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)
    cases = {"cases": [{"tool": "first", "args": {"number": "12"}, "field": "value",
                        "reference_imports": ["import calc._core.Converter"],  # a class, not a module
                        "reference_expr": "calc._core.checksum({number})"}]}
    p = ModelProvider("https://example.invalid/v1", "m", "k")
    body = {"choices": [{"message": {"role": "assistant", "content": json.dumps(cases)}, "finish_reason": "stop"}]}
    p._client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    out = run_tester(p, analysis, _spec(_tool("first")))
    assert out.cases[0].reference_imports == ["import calc._core"]


def test_too_deep_generated_module_is_skipped_not_fatal(tmp_path):
    # Generated code (e.g. huge lookup expressions) can parse but nest too deeply to walk; analysis must go on.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg/ok.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "pkg/generated.py").write_text("x = " + " + ".join(["a"] * 1500) + "\n", encoding="utf-8")
    a = analyze(tmp_path)
    assert "pkg.ok.add" in {s.id for s in a.symbols}
    assert "pkg.generated" not in {m.name for m in a.modules}
    assert any("generated.py" in w and "too deeply" in w for w in a.warnings)
