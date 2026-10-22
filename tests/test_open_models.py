"""Offline tests for the open-weight model policy check.

The check reads committed config, skill provenance and evaluation reports. It never calls a model
host, so these tests use temporary directories only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_open_models import main, scan  # noqa: E402


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_clean_repo(root: Path) -> None:
    _write(root / ".env.example", "# never use gemini or gpt ids here\nMODEL_NAME=gemma-4-26b-a4b-it\n")
    _write(root / "skills" / "iban" / "provenance.json",
           json.dumps({"model": "gemma-4-26b-a4b-it@generativelanguage.googleapis.com"}))
    _write(root / "eval" / "results" / "run.md",
           "# Eval run\n\nSuite: stdnum · model: `gemma-4-26b-a4b-it@host` · tasks/category: 6\n")
    _write(root / "eval" / "results" / "run.jsonl",
           json.dumps({"task_id": "iban-1", "model": "gemma-4-26b-a4b-it@host"}) + "\n")


def test_clean_config_provenance_and_reports_pass(tmp_path, capsys):
    _write_clean_repo(tmp_path)
    assert scan(tmp_path) == []
    assert main(["--root", str(tmp_path)]) == 0
    assert "OK: no proprietary models" in capsys.readouterr().out


def test_proprietary_model_in_config_is_reported(tmp_path):
    _write(tmp_path / ".env.example", "MODEL_NAME=gpt-4o\n")
    findings = scan(tmp_path)
    assert [(f.path, f.field, f.model) for f in findings] == [(".env.example", "MODEL_NAME", "gpt-4o")]


def test_proprietary_fallback_and_embedding_models_are_reported(tmp_path):
    _write(tmp_path / ".env", "\n".join([
        "MODEL_NAME=gemma-4-26b-a4b-it",
        "FALLBACK_MODEL_NAME=openai/gpt-5",
        "EMBED_MODEL=gemini-embedding-001",
    ]) + "\n")
    assert {f.field for f in scan(tmp_path)} == {"FALLBACK_MODEL_NAME", "EMBED_MODEL"}


def test_proprietary_model_in_skill_provenance_is_reported(tmp_path):
    _write(tmp_path / "workspace" / "library" / "iban" / "provenance.json",
           json.dumps({"model": "claude-3-5-sonnet@host"}))
    findings = scan(tmp_path)
    assert [(f.path, f.field, f.model) for f in findings] == [
        ("workspace/library/iban/provenance.json", "model", "claude-3-5-sonnet@host"),
    ]


def test_proprietary_model_in_eval_markdown_is_reported(tmp_path):
    _write(tmp_path / "eval" / "results" / "run.md", "Model: `gpt-5@host` (closed)\n")
    findings = scan(tmp_path)
    assert [(f.path, f.field, f.model) for f in findings] == [("eval/results/run.md", "model", "gpt-5@host")]


def test_proprietary_model_in_eval_jsonl_is_reported(tmp_path):
    _write(tmp_path / "eval" / "results" / "run.jsonl",
           json.dumps({"task_id": "x", "model": "gemini-3.5-flash@host"}) + "\n")
    findings = scan(tmp_path)
    assert [(f.path, f.field, f.model) for f in findings] == [
        ("eval/results/run.jsonl", "model", "gemini-3.5-flash@host"),
    ]


def test_comment_only_mentions_are_ignored(tmp_path):
    _write(tmp_path / ".env.example",
           "# gemini-1.5 and claude-3 are not allowed; use open weights\nMODEL_NAME=qwen/qwen3-32b\n")
    assert scan(tmp_path) == []


def test_proprietary_marker_is_reported_even_when_the_name_is_unknown(tmp_path):
    _write(tmp_path / "skills" / "custom" / "provenance.json",
           json.dumps({"model": "custom-model@host [PROPRIETARY - experiment only]"}))
    findings = scan(tmp_path)
    assert len(findings) == 1 and "PROPRIETARY" in findings[0].model


def test_unreadable_provenance_is_reported_instead_of_skipped(tmp_path):
    _write(tmp_path / "skills" / "broken" / "provenance.json", "{not json")
    findings = scan(tmp_path)
    assert [(f.path, f.field) for f in findings] == [("skills/broken/provenance.json", "provenance")]


def test_main_prints_each_finding_and_exits_nonzero(tmp_path, capsys):
    _write(tmp_path / ".env.example", "MODEL_NAME=gpt-4o\n")
    assert main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Proprietary model references found" in out
    assert ".env.example: MODEL_NAME: gpt-4o" in out
