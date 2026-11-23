"""Sandbox integration tests (need Docker and the zyven-sandbox image). Enabled with ZYVEN_DOCKER_TESTS=1."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.sandbox.runner import run, run_upstream_tests  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("ZYVEN_DOCKER_TESTS") != "1", reason="set ZYVEN_DOCKER_TESTS=1")

PY_NEPALI = ("https://github.com/opensource-nepal/py-nepali", "3ff19477150ea597d6ce2e9d3dce62e6cf0065e6")


@pytest.fixture(scope="session")
def py_nepali(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("repos") / "py-nepali"
    subprocess.run(["git", "clone", "--quiet", PY_NEPALI[0], str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "checkout", "--quiet", PY_NEPALI[1]], check=True)
    d.chmod(0o755)
    return d


def test_upstream_tests_pass_in_sandbox(py_nepali):
    rep = run_upstream_tests(py_nepali, ["tests/test_date_converter.py", "tests/test_phone_number.py"])
    assert rep.passed and rep.ran == 68, rep.tail


def test_sandbox_has_no_network_and_is_not_root(tmp_path):
    tmp_path.chmod(0o755)
    r = run(["python", "-c", "import os, urllib.request\nprint('uid', os.getuid())\n"
             "urllib.request.urlopen('https://pypi.org', timeout=5)"], {tmp_path: "/src"})
    assert "uid 1000" in r.stdout
    assert r.exit_code != 0  # name resolution fails: --network none


def test_source_mount_is_read_only(py_nepali):
    r = run(["sh", "-c", "touch /src/x"], {py_nepali: "/src"})
    assert r.exit_code != 0 and "Read-only" in (r.stderr + r.stdout)


PROBE_SERVER = '''
import json, os, socket
from mcp.server.mcpserver import MCPServer

server = MCPServer(name="probe")


def _try(fn):
    try:
        fn()
        return "allowed"
    except Exception as e:
        return "blocked: " + type(e).__name__


@server.tool(name="probe")
def probe() -> dict:
    """Reports what this server can do from inside its runtime."""
    import zyven_probe_lib  # importable only through PYTHONPATH=/src
    return {
        "uid": os.getuid(),
        "network": _try(lambda: socket.create_connection(("1.1.1.1", 53), timeout=3)),
        "write_skill": _try(lambda: open("/skill/x", "w").write("x")),
        "write_src": _try(lambda: open("/src/x", "w").write("x")),
        "write_tmp": _try(lambda: open("/tmp/x", "w").write("x")),
        "library_value": zyven_probe_lib.VALUE,
    }


if __name__ == "__main__":
    server.run("stdio")
'''


@pytest.mark.anyio
async def test_skills_run_isolated_at_runtime(tmp_path):
    """A skill launched the way the agent launches it gets the verification sandbox: no network, non-root,
    read-only skill and source mounts, only /tmp writable, and its pinned source importable."""
    import json

    from zyven.agent.mcp_tools import ToolBox
    from zyven.memory.skills import skill_server_spec

    skill, src = tmp_path / "skill", tmp_path / "src"
    skill.mkdir()
    src.mkdir()
    (skill / "server.py").write_text(PROBE_SERVER, encoding="utf-8")
    (src / "zyven_probe_lib.py").write_text("VALUE = 42\n", encoding="utf-8")
    for d in (tmp_path, skill, src):
        d.chmod(0o755)
    (skill / "server.py").chmod(0o644)
    (src / "zyven_probe_lib.py").chmod(0o644)

    async with ToolBox() as tb:
        names = await tb.add_server(skill_server_spec("probe", skill, src))
        assert names == ["probe"]
        ok, out = await tb.call("probe", {})
    assert ok, out
    r = json.loads(out)
    r = r.get("result", r)  # dict results may be wrapped, depending on the MCP version
    assert r["uid"] == 1000
    assert r["network"].startswith("blocked")
    assert r["write_skill"].startswith("blocked") and r["write_src"].startswith("blocked")
    assert r["write_tmp"] == "allowed"
    assert r["library_value"] == 42


def test_reference_programs_are_run_against_the_library(tmp_path):
    """A reference that misuses the library (#101: a date string where the constructor takes year, month and day) is
    reported with the exception and the program as it ran; a valid one passes; a static problem is caught first."""
    from zyven.ai.schemas import CapabilitySpec, DiffCase, ReturnField, ToolParam, ToolSpec
    from zyven.compiler.verify import reference_problems

    lib = tmp_path / "lib"
    (lib / "minical").mkdir(parents=True)
    (lib / "minical" / "__init__.py").write_text("")
    (lib / "minical" / "dates.py").write_text(
        "class Day:\n    def __init__(self, year, month, day):\n        self.year, self.month, self.day = year, month, day\n"
        "    def iso(self):\n        return f'{self.year:04d}-{self.month:02d}-{self.day:02d}'\n")
    for p in (tmp_path, lib, lib / "minical"):
        p.chmod(0o755)

    def case(expr: str, args: dict) -> DiffCase:
        return DiffCase(tool="to_iso", args=args, field="iso", reference_imports=["import minical.dates"],
                        reference_expr=expr)

    params = [ToolParam(name="date", type="string", description="", required=False)] + [
        ToolParam(name=n, type="integer", description="", required=False) for n in ("y", "m", "d")]
    spec = CapabilitySpec(name="minical", title="", summary="", included_symbols=[], relevant_tests=[], tools=[
        ToolSpec(name="to_iso", description="", params=params, returns=[ReturnField(name="iso", type="string",
                 description="")], implementation_symbols=[], implementation_notes="", example_args={})])
    cases = [case("minical.dates.Day({date})", {"date": "2024-09-02"}),
             case("minical.dates.Day({y}, {m}, {d}).iso()", {"y": 2024, "m": 9, "d": 2}),
             case("print(minical.dates.Day({y}, 1, 1))", {"y": 2024}),
             # an integer parameter written as text is typed first, as the differential gate does: "{m:02d}" works
             case("minical.dates.Day({y}, {m}, {d}).iso()", {"y": 2024, "m": "9", "d": 2})]
    work = tmp_path / "work"
    problems = reference_problems(cases, spec, lib, ".", {"minical"}, work)
    assert problems[0] is not None and "TypeError" in problems[0]
    assert "minical.dates.Day('2024-09-02')" in problems[0]  # the program as it ran, placeholders filled in
    assert problems[1] is None
    assert problems[2] is not None and "print" in problems[2]  # static check, never sent to the sandbox
    assert problems[3] is None


def test_a_misused_constructor_is_sent_back_and_fixed_without_a_model(tmp_path, monkeypatch):
    """#101 end to end: the Tester's first reference passes a date string where the constructor takes year, month and
    day. Only running it shows that. The sandbox run catches it, the re-ask quotes the TypeError and the real
    signature, and the scripted second answer gives the tool a valid case. No model is called."""
    import zyven.compiler.pipeline as pl
    from zyven.ai.schemas import CapabilitySpec, DiffCase, DiffTests, ReturnField, ToolParam, ToolSpec
    from zyven.analysis.analyzer import analyze
    from zyven.compiler.verify import reference_problems

    lib = tmp_path / "lib"
    (lib / "minical").mkdir(parents=True)
    (lib / "minical" / "__init__.py").write_text("")
    (lib / "minical" / "dates.py").write_text(
        "class GregorianDate:\n    def __init__(self, year, month, day):\n"
        "        self.year, self.month, self.day = year, month, day\n"
        "    def weekday(self):\n        import datetime\n"
        "        return datetime.date(self.year, self.month, self.day).isoweekday()\n")
    for p in (tmp_path, lib, lib / "minical"):
        p.chmod(0o755)
    a = analyze(lib)
    spec = CapabilitySpec(name="weekdays", title="", summary="", included_symbols=[], relevant_tests=[], tools=[
        ToolSpec(name="weekday_of", description="", params=[ToolParam(name="date", type="string", description="")],
                 returns=[ReturnField(name="weekday", type="integer", description="")],
                 implementation_symbols=["minical.dates.GregorianDate.weekday"], implementation_notes="",
                 example_args={"date": "2024-09-02"})])
    first = DiffCase(tool="weekday_of", args={"date": "2024-09-02"}, field="weekday",
                     reference_imports=["import minical.dates"],
                     reference_expr="minical.dates.GregorianDate({date}).weekday()")
    second = first.model_copy(update={"reference_expr":
                                      "y, m, d = map(int, {date}.split('-'))\nminical.dates.GregorianDate(y, m, d).weekday()"})
    asked = []

    def scripted_tester(provider, analysis, sub, feedback="", followups=True):
        asked.append(feedback)
        return DiffTests(cases=[second])

    monkeypatch.setattr(pl, "tester", scripted_tester)

    def check(cases):
        return reference_problems(cases, spec, lib, ".", {"minical"}, tmp_path / "work")

    out, problems = pl._reask_unusable(None, a, spec, DiffTests(cases=[first]), check, lambda *x, **k: None)
    assert len(asked) == 1
    assert "TypeError" in asked[0] and "GregorianDate('2024-09-02')" in asked[0]
    assert "minical.dates.GregorianDate(year, month, day)" in asked[0]
    assert problems == [problems[0], None] and problems[0] is not None
    assert out.cases[1].reference_expr == second.reference_expr


def test_a_compile_recovers_from_a_misused_constructor(tmp_path):
    """The whole pipeline with scripted roles (no model): the Tester's first answer misuses the constructor, the
    compile runs it in the sandbox before any gate, re-asks once, and the skill is verified on the second answer."""
    from types import SimpleNamespace

    from zyven.ai.schemas import (AdapterCode, CapabilitySpec, DiffCase, DiffTests, ReturnField, ToolImpl, ToolParam,
                                  ToolSpec)
    from zyven.analysis.analyzer import analyze
    from zyven.compiler.pipeline import compile_capability

    lib = tmp_path / "lib"
    (lib / "minical").mkdir(parents=True)
    (lib / "minical" / "__init__.py").write_text("")
    (lib / "minical" / "dates.py").write_text(
        "import datetime\n\n\nclass GregorianDate:\n    def __init__(self, year, month, day):\n"
        "        self.d = datetime.date(year, month, day)\n\n    def weekday(self):\n        return self.d.isoweekday()\n")
    for p in (tmp_path, lib, lib / "minical"):
        p.chmod(0o755)
    spec = CapabilitySpec(name="weekdays", title="Weekdays", summary="s", included_symbols=[], relevant_tests=[], tools=[
        ToolSpec(name="weekday_of", description="ISO weekday of a date",
                 params=[ToolParam(name="date", type="string", description="YYYY-MM-DD")],
                 returns=[ReturnField(name="weekday", type="integer", description="1 = Monday")],
                 implementation_symbols=["minical.dates.GregorianDate.weekday"], implementation_notes="",
                 example_args={"date": "2024-09-02"})])
    adapter = AdapterCode(tools=[ToolImpl(tool="weekday_of", imports=["import minical.dates"], body=(
        "y, m, d = (int(x) for x in date.strip().split('-'))\n"
        "return {'weekday': minical.dates.GregorianDate(y, m, d).weekday()}"))])

    def case(expr: str) -> DiffCase:
        return DiffCase(tool="weekday_of", args={"date": "2024-09-02"}, field="weekday",
                        reference_imports=["import minical.dates"], reference_expr=expr)

    answers = [DiffTests(cases=[case("minical.dates.GregorianDate({date}).weekday()")]),  # the #101 misuse
               DiffTests(cases=[case("y, m, d = map(int, {date}.split('-'))\n"
                                     "minical.dates.GregorianDate(y, m, d).weekday()")])]
    prompts = []

    class Scripted:
        label = "scripted@test"
        stats = SimpleNamespace(calls=0)

        def generate_structured(self, messages, schema, **kw):
            self.stats.calls += 1
            if schema is AdapterCode:
                return adapter
            prompts.append(messages[-1]["content"])
            return answers.pop(0)

    events = []
    r = compile_capability(Scripted(), analyze(lib), spec=spec, skills_root=tmp_path / "skills", run_upstream=False,
                           on_event=lambda kind, data: events.append((kind, data.get("detail", ""))))
    kinds = [k for k, _ in events]
    assert "tester.retry" in kinds and "tester.retry.done" in kinds
    assert "1 valid case(s) added for 1/1" in dict(events)["tester.retry.done"]
    assert prompts[0].startswith("CAPABILITY SPEC") and "HOW TO BUILD THE LIBRARY'S OBJECTS" in prompts[0]
    assert "minical.dates.GregorianDate(year, month, day)" in prompts[1] and "TypeError" in prompts[1]
    assert r.verified, events
