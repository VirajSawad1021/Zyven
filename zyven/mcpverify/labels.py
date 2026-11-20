"""One row per `zyven verify` finding, for labelling by hand.

A precision study labels each finding as a real problem, only a capability, or a false alarm, then counts per rule.
Rows are built from the SARIF output, so a row and a code-scanning alert always agree on the rule and the level.
"""

from __future__ import annotations

import csv
from pathlib import Path

from zyven.mcpverify.checks import Report
from zyven.mcpverify.sarif import to_sarif

COLUMNS = ["server", "target", "check", "rule", "level", "finding", "label", "note"]


def finding_rows(server: str, report: Report) -> list[dict[str, str]]:
    """Rows for one server; `label` and `note` are left empty for the person labelling."""
    shown = " ".join(x for x in (report.server.get("name"), report.server.get("version")) if x) or report.target
    rows = []
    for res in to_sarif([(report, "mcp-server")])["runs"][0]["results"]:
        text = res["message"]["text"]
        text = text[len(shown) + 2:] if text.startswith(f"{shown}: ") else text
        rows.append({"server": server, "target": report.target, "check": res["ruleId"].split("/")[0],
                     "rule": res["ruleId"], "level": res["level"], "finding": text, "label": "", "note": ""})
    return rows


def append_rows(path: Path, rows: list[dict[str, str]]) -> int:
    """Append to a UTF-8 CSV file; the header is written only when the file is new or empty."""
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)
