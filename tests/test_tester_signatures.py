"""The Tester is shown how to build the library's objects, and a reference that misuses the library comes back with
the exact signatures it needed (#101). Offline: the sandbox run is replaced by a fixed check."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.ai.schemas import CapabilitySpec, DiffCase, DiffTests, ReturnField, ToolParam, ToolSpec  # noqa: E402
from zyven.analysis.analyzer import analyze  # noqa: E402
from zyven.analysis.miner import construction_signatures, describe_symbols  # noqa: E402

FILES = {
    "minical/__init__.py": "from minical.dates import GregorianDate\nfrom minical._impl import Thing\n",
    "minical/_impl.py": "class Thing:\n    def __init__(self, size):\n        self.size = size\n",
    "minical/dates.py": '''
        import abc


        class DateError(ValueError):
            """Raised for an impossible date."""


        class BaseDate(abc.ABC):
            """Any date."""

            def holiday(self):
                return None


        class _Cache:
            pass


        class CalendarDate(BaseDate):
            def __init__(self, year, month, day):
                self.year, self.month, self.day = year, month, day


        class GregorianDate(CalendarDate):
            """A Gregorian date (year, month, day)."""

            @classmethod
            def from_iso(kls, text):
                return kls(*map(int, text.split("-")))

            @staticmethod
            def today():
                return GregorianDate(2024, 1, 1)

            def _private_factory(self):
                return self
        ''',
    "minical/cal.py": '''
        def holiday(date, israel=False):
            """Holiday on a date.

            Parameters
            ----------
            date : minical.dates.BaseDate
            """
            return date.holiday()
        ''',
    "tests/test_dates.py": '''
        import minical.cal as mc
        from minical.dates import GregorianDate


        def test_date():
            d = GregorianDate(2024, 9, 2)
            assert d.year == 2024
        ''',
}


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    root = tmp_path_factory.mktemp("minical")
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return analyze(root)


def _spec() -> CapabilitySpec:
    return CapabilitySpec(name="holidays", title="Holidays", summary="s", included_symbols=[], relevant_tests=[], tools=[
        ToolSpec(name="holiday_on", description="d", params=[ToolParam(name="date", type="string", description="x")],
                 returns=[ReturnField(name="holiday", type="string", description="v")],
                 implementation_symbols=["minical.cal.holiday"], implementation_notes="",
                 example_args={"date": "2024-09-02"})])


def test_a_documented_base_class_brings_its_buildable_subclasses(analysis):
    text = construction_signatures(analysis, ["minical.cal.holiday"])
    # named only in the docstring, abstract, so its subclasses follow, with the inherited constructor
    assert "minical.dates.BaseDate(...)" in text and "abstract: build one of its subclasses" in text
    assert "minical.dates.GregorianDate(year, month, day)  (constructor inherited from minical.dates.CalendarDate)" in text
    assert "minical.dates.GregorianDate.from_iso(text)  (classmethod)" in text  # `kls` dropped like `cls`
    assert "minical.dates.GregorianDate.today()  (staticmethod)" in text
    assert "_private_factory" not in text and "_Cache" not in text  # a caller never builds these
    assert "DateError" not in text  # nor exceptions
    assert "tests/test_dates.py:6: d = GregorianDate(2024, 9, 2)" in text  # a real call from the upstream tests


def test_a_method_is_described_with_how_to_build_its_class(analysis):
    lines = describe_symbols(analysis, ["minical.dates.BaseDate.holiday", "minical.dates.GregorianDate"])
    assert lines[0] == "minical.dates.BaseDate.holiday()"
    assert any(x.startswith("minical.dates.GregorianDate(year, month, day)") for x in lines)


def test_the_signatures_lead_the_testers_evidence_and_are_never_cut(analysis, monkeypatch):
    import zyven.ai.roles as roles
    monkeypatch.setattr(roles, "evidence_packet", lambda a, ids, max_chars=0: "x" * 50000)  # huge source evidence
    text = roles._tester_evidence(analysis, _spec())
    assert text.startswith("HOW TO BUILD THE LIBRARY'S OBJECTS")
    assert "minical.dates.GregorianDate(year, month, day)" in text.split("\n\n")[0]


def test_reference_names_follow_its_imports_and_name_what_does_not_exist(analysis):
    from zyven.analysis.refs import RefResolver
    from zyven.compiler.pipeline import reference_names
    c = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday",
                 reference_imports=["from minical.dates import GregorianDate as G", "import minical.cal"],
                 reference_expr="d = G.fromisoformat({date})\nminical.cal.holiday(G({date}))")
    found, unknown = reference_names(c, analysis, RefResolver(analysis))
    assert set(found) == {"minical.dates.GregorianDate", "minical.cal.holiday"}
    assert unknown == ["minical.dates.GregorianDate.fromisoformat"]


def test_a_runtime_failure_is_sent_back_with_the_signature_it_needed(analysis, monkeypatch):
    """#101: the reference misused the constructor, which only running it shows. The re-ask quotes the exception and
    the constructor's real signature; the case the Tester then writes is kept only if it is valid."""
    import zyven.compiler.pipeline as pl
    wrong = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday",
                     reference_imports=["import minical.dates", "import minical.cal"],
                     reference_expr="minical.cal.holiday(minical.dates.GregorianDate({date}))")
    right = wrong.model_copy(update={"reference_expr": "minical.cal.holiday(minical.dates.GregorianDate.from_iso({date}))"})
    asked = {}

    def fake_tester(provider, a, sub, feedback="", followups=True):
        asked.update(feedback=feedback)
        return DiffTests(cases=[right])

    def check(cases):  # stands in for the sandbox: the misuse raises, the factory call works
        return [None if "from_iso" in c.reference_expr else
                "TypeError(\"__init__() missing 2 required positional arguments: 'month' and 'day'\") running: "
                "minical.cal.holiday(minical.dates.GregorianDate('2024-09-02'))" for c in cases]

    monkeypatch.setattr(pl, "tester", fake_tester)
    out, problems = pl._reask_unusable(None, analysis, _spec(), DiffTests(cases=[wrong]), check, lambda *a, **k: None)
    fb = asked["feedback"]
    assert "TypeError" in fb and "GregorianDate('2024-09-02')" in fb
    assert "minical.dates.GregorianDate(year, month, day)" in fb
    assert "minical.cal.holiday(date, israel = False)" in fb
    assert [c.reference_expr for c in out.cases] == [wrong.reference_expr, right.reference_expr]
    assert problems[0] is not None and problems[1] is None


def test_an_added_case_that_still_fails_is_not_kept(analysis, monkeypatch):
    import zyven.compiler.pipeline as pl
    wrong = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday", reference_imports=[],
                     reference_expr="minical.cal.holiday(minical.dates.GregorianDate({date}))")
    monkeypatch.setattr(pl, "tester", lambda *a, **k: DiffTests(cases=[wrong]))
    out, problems = pl._reask_unusable(None, analysis, _spec(), DiffTests(cases=[wrong]),
                                       lambda cases: ["TypeError()"] * len(cases), lambda *a, **k: None)
    assert len(out.cases) == 1 and problems == ["TypeError()"]


def test_a_name_error_is_answered_with_the_import_it_needs(analysis):
    """Most of E4B's invalid hijridate references used `Hijri` after importing only the module, and networkx ones used
    `nx` without `import networkx as nx`. The re-ask names the missing line; it never edits the reference."""
    from zyven.compiler.pipeline import missing_import

    def run(name):
        return missing_import(f"NameError(\"name '{name}' is not defined\") running: {name}(1)", analysis)

    name, advice, ids = run("GregorianDate")
    assert advice == "add `from minical.dates import GregorianDate` to reference_imports"
    assert ids == ["minical.dates.GregorianDate"]  # so its signature is quoted too
    assert run("Thing")[1] == "add `from minical import Thing` to reference_imports"  # public re-export, not _impl
    assert run("mc")[1] == "add `import minical.cal as mc` to reference_imports"  # the alias the library's tests use
    assert run("G")[1] == "define `G` in the reference's own setup lines before the last line uses it"
    assert missing_import("TypeError('x') running: f()", analysis) == ("", "", [])


def test_the_reask_carries_the_import_hint(analysis, monkeypatch):
    import zyven.compiler.pipeline as pl
    wrong = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday", reference_imports=["import minical.cal"],
                     reference_expr="minical.cal.holiday(GregorianDate.from_iso({date}))")
    asked = {}
    monkeypatch.setattr(pl, "tester", lambda p, a, sub, feedback="", followups=True:
                        asked.update(feedback=feedback) or DiffTests(cases=[]))
    pl._reask_unusable(None, analysis, _spec(), DiffTests(cases=[wrong]),
                       lambda cases: ["NameError(\"name 'GregorianDate' is not defined\") running: ..."] * len(cases),
                       lambda *a, **k: None)
    fb = asked["feedback"]
    assert "`GregorianDate` is not defined in that reference: add `from minical.dates import GregorianDate`" in fb
    assert "minical.dates.GregorianDate(year, month, day)" in fb


def test_every_library_module_a_reference_reaches_is_imported():
    """`import pyluach` does not load pyluach.hebrewcal; E4B lost pyluach references to that AttributeError."""
    from zyven.ai.roles import used_modules
    mods = {"pyluach", "pyluach.dates", "pyluach.hebrewcal"}
    program = "pyluach.hebrewcal.holiday(pyluach.dates.GregorianDate(2023, 4, 5), israel=False)"
    assert set(used_modules(program, {"pyluach"}, mods)) == {"pyluach.hebrewcal", "pyluach.dates", "pyluach"}
    assert used_modules("pyluach = 1\npyluach.real", {"pyluach"}, mods) == []  # a name the program binds itself
    assert used_modules("broken(", {"pyluach"}, mods) == []


def test_the_tester_adds_the_submodule_imports(analysis, monkeypatch):
    import zyven.ai.roles as roles
    case = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday", reference_imports=["import minical"],
                    reference_expr="minical.cal.holiday(minical.dates.GregorianDate.from_iso({date}))")

    class One:
        label = "one"

        def generate_structured(self, messages, schema, **kw):
            return DiffTests(cases=[case.model_copy()])

    out = roles.tester(One(), analysis, _spec(), followups=False)
    assert out.cases[0].reference_imports == ["import minical", "import minical.cal", "import minical.dates"]


def test_a_tool_argument_used_as_a_variable_is_pointed_at_its_placeholder(analysis):
    """E4B wrote `GregorianDate(date_str[0:4], ...)` and `validate(iban_string)`: the tool's argument as a variable."""
    from zyven.compiler.pipeline import missing_import
    name, advice, ids = missing_import("NameError(\"name 'date_str' is not defined\") running: f(date_str)", analysis,
                                       {"date_str"})
    assert name == "date_str" and "{date_str}" in advice and ids == []


def test_the_reask_asks_once_per_tool_and_skips_tools_without_parameters(analysis, monkeypatch):
    import zyven.compiler.pipeline as pl
    base = _spec().tools[0]
    spec = _spec().model_copy(update={"tools": [base, base.model_copy(update={"name": "festival_on"}),
                                                base.model_copy(update={"name": "today", "params": [],
                                                                        "example_args": {}})]})
    asked = []

    def fake_tester(provider, a, sub, feedback="", followups=True):
        asked.append([t.name for t in sub.tools])
        return DiffTests(cases=[])

    monkeypatch.setattr(pl, "tester", fake_tester)
    pl._reask_unusable(None, analysis, spec, DiffTests(cases=[]), lambda cases: [None] * len(cases),
                       lambda *a, **k: None)
    assert asked == [["holiday_on"], ["festival_on"]]  # one focused request each; `today` can never get a case


def test_a_call_chained_onto_none_is_answered_with_the_multi_line_form(analysis, monkeypatch):
    """review of #108: E4B wrote every networkx reference as `nx.Graph().add_weighted_edges_from([...]).f(...)`, and
    add_weighted_edges_from returns None. The re-ask names that pattern and shows the multi-line form."""
    import zyven.compiler.pipeline as pl
    why = ("AttributeError(\"'NoneType' object has no attribute 'dijkstra_path_length'\") running: "
           "networkx.Graph().add_weighted_edges_from([]).dijkstra_path_length('A', 'C')")
    assert "`.dijkstra_path_length` returned None" in pl.none_chain_hint(why)
    assert pl.none_chain_hint("AttributeError(\"'Graph' object has no attribute 'x'\")") == ""
    wrong = DiffCase(tool="holiday_on", args={"date": "2024-09-02"}, field="holiday", reference_imports=[],
                     reference_expr="minical.cal.Calendar().add({date}).holiday()")
    asked = {}
    monkeypatch.setattr(pl, "tester", lambda p, a, sub, feedback="", followups=True:
                        asked.update(feedback=feedback) or DiffTests(cases=[]))
    pl._reask_unusable(None, analysis, _spec(), DiffTests(cases=[wrong]), lambda cases: [why] * len(cases),
                       lambda *a, **k: None)
    assert "never chain onto it" in asked["feedback"] and "obj.add_items({items})" in asked["feedback"]


def test_a_syntax_error_quotes_the_program():
    """An IBAN run lost every case to `syntax error: invalid syntax` with nothing to show which program; the problem
    now carries it, for the re-ask and for the eval results."""
    from zyven.compiler.verify import reference_problem
    c = DiffCase(tool="t", args={"x": 1}, field="f", reference_imports=[], reference_expr="calc.f({x}")
    why = reference_problem(c, {"calc"})
    assert why.startswith("syntax error: ") and why.endswith("in: calc.f({x}")
