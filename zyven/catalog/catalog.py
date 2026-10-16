"""Curated repository catalog: pinned repos Zyven may compile from, pre-analyzed and pre-scouted.

Repos are cloned at a pinned commit during `sync` (network), never during a task. A task only
searches the cached scout results, so untrusted code is never fetched on the agent's behalf.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from zyven.agent.gap import Option
from zyven.ai.provider import ModelProvider
from zyven.ai.roles import scout
from zyven.ai.schemas import CandidateCapability, ScoutResult
from zyven.analysis.analyzer import Analysis, analyze


@dataclass
class CatalogRepo:
    name: str
    url: str
    commit: str
    license: str
    note: str = ""
    curated: list[dict] = field(default_factory=list)  # reviewer-edited capabilities (name/title/description/entry_points)
    hide: list[str] = field(default_factory=list)  # scout proposals a reviewer rejected


class Catalog:
    def __init__(self, catalog_file: Path, workspace: Path) -> None:
        self.file = Path(catalog_file)
        self.workspace = Path(workspace)
        self.repos = [CatalogRepo(**r) for r in json.loads(self.file.read_text(encoding="utf-8"))["repos"]]

    def checkout_dir(self, repo: CatalogRepo) -> Path:
        return self.workspace / "repos" / repo.name

    def scout_file(self, repo: CatalogRepo) -> Path:
        return self.workspace / "runs" / repo.name / "scout.json"

    def sync(self, provider: ModelProvider | None = None, rescout: bool = False) -> list[str]:
        """Clone missing repos at their pinned commit and cache scout results. Returns log lines."""
        log = []
        for r in self.repos:
            d = self.checkout_dir(r)
            if not (d / ".git").exists():
                d.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", "--quiet", r.url, str(d)], check=True)
                log.append(f"cloned {r.name}")
            subprocess.run(["git", "-C", str(d), "checkout", "--quiet", r.commit], check=True)
            sf = self.scout_file(r)
            if provider and (rescout or not sf.exists()):
                sf.parent.mkdir(parents=True, exist_ok=True)
                res = scout(provider, analyze(d))
                sf.write_text(res.value.model_dump_json(indent=1), encoding="utf-8")
                log.append(f"scouted {r.name}: {len(res.value.capabilities)} capabilities")
        return log

    def capabilities(self, r: CatalogRepo) -> list[CandidateCapability]:
        """Scout proposals, with reviewer-curated entries added/replacing and hidden ones removed."""
        sf = self.scout_file(r)
        caps = ScoutResult.model_validate_json(sf.read_text(encoding="utf-8")).capabilities if sf.exists() else []
        curated = [CandidateCapability(why_agents_need_it="curated by a reviewer", **c) for c in r.curated]
        names = {c.name for c in curated} | set(r.hide)
        return curated + [c for c in caps if c.name not in names]

    def options(self) -> list[Option]:
        return [Option(id=f"{r.name}:{c.name}", title=c.title, description=c.description)
                for r in self.repos for c in self.capabilities(r)]

    def resolve(self, option_id: str) -> tuple[CatalogRepo, CandidateCapability, Analysis]:
        repo_name, cap_name = option_id.split(":", 1)
        r = next(x for x in self.repos if x.name == repo_name)
        return r, next(c for c in self.capabilities(r) if c.name == cap_name), analyze(self.checkout_dir(r))
