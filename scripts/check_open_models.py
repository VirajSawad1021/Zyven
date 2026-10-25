#!/usr/bin/env python3
"""Fail if a proprietary model appears in config, skill provenance or eval reports.

Issue #7 requires open-weight models end to end. This check is deterministic and offline: it reads
the committed configuration, every skill provenance record, and the evaluation reports, and exits
non-zero if any model identifier is proprietary.

Usage:
    uv run python scripts/check_open_models.py
    uv run python scripts/check_open_models.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.ai.provider import is_proprietary  # noqa: E402

ENV_KEYS = ("MODEL_NAME", "FALLBACK_MODEL_NAME", "EMBED_MODEL")
JSON_KEYS = ("model", "served_by")
SKIP_PARTS = {".git", ".venv", "node_modules", ".next", "out", "__pycache__", "repos"}
_MODEL_IN_TEXT = re.compile(r"\bmodel\s*:\s*`?([^`\n]+)`?", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    path: str
    field: str
    model: str

    def __str__(self) -> str:
        return f"{self.path}: {self.field}: {self.model}"


def _add(findings: list[Finding], root: Path, path: Path, field: str, model: str) -> None:
    model = model.strip()
    if model and (is_proprietary(model) or "[PROPRIETARY" in model.upper()):
        findings.append(Finding(path.relative_to(root).as_posix(), field, model))


def _scan_env(path: Path, root: Path, findings: list[Finding]) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key in ENV_KEYS:
            _add(findings, root, path, key, value)


def _scan_provenance(path: Path, root: Path, findings: list[Finding]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        findings.append(Finding(path.relative_to(root).as_posix(), "provenance", f"unreadable: {e}"))
        return
    if isinstance(data, dict):
        for key in JSON_KEYS:
            value = data.get(key)
            if isinstance(value, str):
                _add(findings, root, path, key, value)


def _scan_markdown(path: Path, root: Path, findings: list[Finding]) -> None:
    for match in _MODEL_IN_TEXT.finditer(path.read_text(encoding="utf-8")):
        _add(findings, root, path, "model", match.group(1))


def _scan_jsonl(path: Path, root: Path, findings: list[Finding]) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        for key in JSON_KEYS:
            value = record.get(key)
            if isinstance(value, str):
                _add(findings, root, path, key, value)


def _walk(root: Path, name: str):
    for path in sorted(root.rglob(name)):
        if any(part in SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        yield path


def scan(root: Path) -> list[Finding]:
    root = Path(root).resolve()
    findings: list[Finding] = []
    for name in (".env", ".env.example"):
        path = root / name
        if path.exists():
            _scan_env(path, root, findings)
    for path in _walk(root, "provenance.json"):
        _scan_provenance(path, root, findings)
    results = root / "eval" / "results"
    if results.exists():
        for path in sorted(results.glob("*.md")):
            _scan_markdown(path, root, findings)
        for path in sorted(results.glob("*.jsonl")):
            _scan_jsonl(path, root, findings)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    findings = scan(args.root)
    if not findings:
        print("OK: no proprietary models in config, skill provenance or eval reports.")
        return 0
    print("Proprietary model references found:")
    for finding in findings:
        print(f"  {finding}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
