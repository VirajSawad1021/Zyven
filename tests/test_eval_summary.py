"""Offline tests for repeated-run summaries (no model, no Docker)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.run_eval import _fmt_num, _fmt_pct, _mean_half_range, summarize  # noqa: E402


def test_mean_half_range_and_formatting():
    assert _mean_half_range([80, 100]) == (90.0, 10.0)
    assert _mean_half_range([90]) == (90.0, 0.0)
    assert _fmt_pct(90, 10, 2) == "90% ± 10%"
    assert _fmt_pct(90, 0, 1) == "90%"
    assert _fmt_num(12.34, 0.12, 2, 1) == "12.3 ± 0.1"


def _rec(cond, run, cat, correct, error=None, seconds=1.0, tokens_in=5, tokens_out=5):
    return {
        "condition": cond,
        "run": run,
        "category": cat,
        "correct": correct,
        "error": error,
        "seconds": seconds,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "truncated": False,
        "recovered": False,
    }


def test_summarize_reports_per_run_mean_and_half_range():
    records = [
        _rec("no_tools", 1, "x", True), _rec("no_tools", 1, "x", False),
        _rec("no_tools", 1, "y", True), _rec("no_tools", 1, "y", False),
        _rec("no_tools", 2, "x", True), _rec("no_tools", 2, "x", True),
        _rec("no_tools", 2, "y", True), _rec("no_tools", 2, "y", True),
    ]
    by = summarize(records)
    s = by["no_tools"]

    assert s["runs"] == 2
    assert s["cells"]["x"] == (75.0, 25.0)
    assert s["cells"]["y"] == (75.0, 25.0)
    assert s["total"] == (75.0, 25.0)
    assert s["tokens"] == (10.0, 0.0)
