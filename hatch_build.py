"""Wheel build hook: ship the pinned catalog, and the dashboard when it has been built.

The dashboard (`web/out`, a Next.js static export) is a build artifact and not in git, so an install straight from git
has no copy of it; the board then serves its single-file page. Release builds run `npm run build` first (see
.github/workflows/release.yml), so wheels from PyPI carry the full dashboard.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        build_data["force_include"][str(root / "catalog" / "repos.json")] = "zyven/data/catalog/repos.json"
        site = root / "web" / "out"
        if (site / "index.html").exists():
            build_data["force_include"][str(site)] = "zyven/data/site"
