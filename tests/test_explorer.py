"""Offline tests for the repo explorer (static funnel, module graph, candidates)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.analysis.analyzer import analyze  # noqa: E402
from zyven.analysis.explorer import explore  # noqa: E402

FILES = {
    "geo/__init__.py": "",
    "geo/units.py": '''
        """Unit conversion."""


        def km_to_miles(km: float) -> float:
            """Convert kilometres to miles."""
            return km * 0.621371


        def _private(x):
            return x
    ''',
    "geo/io.py": '''
        import os
        from geo.units import km_to_miles


        def read_home():
            """Reads an environment variable (side effect)."""
            return km_to_miles(float(os.environ.get("KM", "1")))
    ''',
    "tests/test_units.py": "from geo.units import km_to_miles\n\n\ndef test_k():\n    assert km_to_miles(0) == 0\n",
}


def _repo(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return tmp_path


def test_funnel_only_narrows_and_excludes_side_effects(tmp_path):
    out = explore(analyze(_repo(tmp_path)), [{"name": "units", "title": "Units", "entry_points": ["geo.units.km_to_miles"]}])
    counts = [s["count"] for s in out["funnel"]]
    assert counts == sorted(counts, reverse=True), counts  # each stage is a subset of the previous one
    ids = [c["id"] for c in out["top_candidates"]]
    assert "geo.units.km_to_miles" in ids
    assert "geo.io.read_home" not in ids  # touches the environment
    assert all("_private" not in i for i in ids)
    assert out["funnel"][-1]["count"] == 1 and out["capability_entry_points_found"] == 1
    cand = next(c for c in out["top_candidates"] if c["id"] == "geo.units.km_to_miles")
    assert cand["tested"] and cand["capability"] == "units" and cand["params"] == ["km"]


def test_graph_edges_connect_shown_nodes_only(tmp_path):
    g = explore(analyze(_repo(tmp_path)))["graph"]
    shown = {n["id"] for n in g["nodes"]}
    assert {"geo.units", "geo.io"} <= shown
    assert all(e["source"] in shown and e["target"] in shown for e in g["edges"])
    assert {"source": "geo.io", "target": "geo.units", "weight": 1} in g["edges"]
