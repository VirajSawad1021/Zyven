"""Skill library: verified skills Zyven has compiled and kept.

A skill directory is listed only if its validation report says it passed. Usage health is recorded
per call so failing skills can be flagged for re-compilation.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from zyven.agent.gap import Option
from zyven.ai.schemas import CapabilitySpec

log = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    dir: Path
    spec: CapabilitySpec
    verified_for: list[str]
    source: str
    source_checkout: str | None = None

    @property
    def server(self) -> Path:
        return self.dir / "server.py"

    def server_spec(self):
        """Launch spec for the agent: wrap-mode skills import their pinned source checkout."""
        return skill_server_spec(self.name, self.dir, self.source_checkout)

    def option(self) -> Option:
        tools = ", ".join(t.name for t in self.spec.tools)
        return Option(id=self.name, title=self.spec.title, description=f"{self.spec.summary} Tools: {tools}")


HOST_RUNTIME_ENV = "ZYVEN_SKILL_RUNTIME"


def skill_server_spec(name: str, skill_dir: Path, source_checkout: str | Path | None):
    """How a compiled skill runs when the agent uses it: in the sandbox, like its verification gates. Running on
    the host is a development-only opt-in (ZYVEN_SKILL_RUNTIME=host) and is logged every time."""
    from zyven.agent.mcp_tools import MCPServerSpec

    if os.environ.get(HOST_RUNTIME_ENV, "").lower() == "host":
        log.warning("%s=host: running skill %r on the host WITHOUT sandbox isolation (development only)",
                    HOST_RUNTIME_ENV, name)
        spec = MCPServerSpec.python_script(name, Path(skill_dir) / "server.py")
        if source_checkout:
            spec.env = {"PYTHONPATH": str(source_checkout)}
        return spec
    return MCPServerSpec.sandboxed(name, skill_dir, source_checkout)


class SkillLibrary:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "usage.sqlite", check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS calls (ts REAL, skill TEXT, tool TEXT, ok INTEGER, task TEXT)")

    def list(self) -> list[Skill]:
        out = []
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            rep, cap = d / "validation-report.json", d / "capability.json"
            if not (rep.exists() and cap.exists() and (d / "server.py").exists()):
                continue
            report = json.loads(rep.read_text(encoding="utf-8"))
            if not report.get("passed"):
                continue
            prov = json.loads((d / "provenance.json").read_text(encoding="utf-8")) if (d / "provenance.json").exists() else {}
            out.append(Skill(d.name, d, CapabilitySpec.model_validate_json(cap.read_text(encoding="utf-8")),
                             report.get("verified_for", []), f"{prov.get('repository')} @ {str(prov.get('commit'))[:7]}",
                             prov.get("source_checkout")))
        return out

    def get(self, name: str) -> Skill | None:
        return next((s for s in self.list() if s.name == name), None)

    def record_call(self, skill: str, tool: str, ok: bool, task: str = "") -> None:
        self._db.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (time.time(), skill, tool, int(ok), task[:200]))
        self._db.commit()

    def health(self) -> dict[str, dict[str, int]]:
        rows = self._db.execute("SELECT skill, SUM(ok), COUNT(*) FROM calls GROUP BY skill").fetchall()
        return {s: {"ok": int(ok or 0), "calls": n} for s, ok, n in rows}
