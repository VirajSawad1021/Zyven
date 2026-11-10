"""Rebuild a compiled skill's server.py with the current harness, then prove it again. No model calls.

A skill folder keeps everything a rebuild needs: the spec (capability.json), the model-written tool bodies
(adapter-code.json), where it came from (provenance.json) and the Tester's differential cases (diff_tests.json). The
harness around the bodies (header, signatures, annotations, parameter schemas) improves over time; reassembling gives an
old skill those improvements without asking a model to write anything.

Nothing unverified ships: the rebuilt server goes through all six gates again with the saved differential cases. If any
gate fails, the old server.py is put back and the skill is reported as kept unchanged.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from zyven import __version__
from zyven.ai.schemas import AdapterCode, CapabilitySpec, DiffCase, DiffTests
from zyven.compiler.build import assemble

FILES = ("capability.json", "adapter-code.json", "provenance.json")


@dataclass
class Result:
    skill: str
    status: str  # "up to date" | "reassembled" | "kept (gates failed)" | "skipped"
    detail: str = ""


def is_skill(d: Path) -> bool:
    return all((d / f).exists() for f in FILES) and (d / "server.py").exists()


def reassemble_one(skill_dir: Path, verify_gates: bool = True, dry_run: bool = False) -> Result:
    name = skill_dir.name
    if not is_skill(skill_dir):
        return Result(name, "skipped", f"not a compiled skill (needs server.py and {', '.join(FILES)})")
    spec = CapabilitySpec.model_validate_json((skill_dir / "capability.json").read_text(encoding="utf-8"))
    code = AdapterCode.model_validate_json((skill_dir / "adapter-code.json").read_text(encoding="utf-8"))
    prov = json.loads((skill_dir / "provenance.json").read_text(encoding="utf-8"))
    old = (skill_dir / "server.py").read_text(encoding="utf-8")
    new = assemble(spec, code, prov)
    if new == old:
        return Result(name, "up to date")
    if dry_run:
        return Result(name, "would reassemble", f"{len(old.splitlines())} -> {len(new.splitlines())} lines")
    backup = skill_dir / "server.py.before-reassemble"
    shutil.copyfile(skill_dir / "server.py", backup)
    (skill_dir / "server.py").write_text(new, encoding="utf-8")
    if verify_gates:
        try:
            report, why = _verify(skill_dir, spec, prov)
        except Exception as e:  # noqa: BLE001  a crash must never leave an unverified server in place
            report, why = None, f"{type(e).__name__}: {str(e)[:200]}"
        if report is None or not report.passed:
            shutil.move(backup, skill_dir / "server.py")
            failed = why or ", ".join(g.name for g in report.gates if not g.passed)
            return Result(name, "kept (gates failed)", f"old server.py restored; failed: {failed}")
        (skill_dir / "validation-report.json").write_text(
            json.dumps(report.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        detail = "6 gates passed again: " + ", ".join(g.name for g in report.gates)
    else:
        detail = "gates NOT rerun (--no-verify)"
    prov.setdefault("reassembled", []).append({"generator": f"zyven {__version__}", "at": time.strftime("%Y-%m-%d"),
                                               "gates_rerun": verify_gates})
    (skill_dir / "provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    backup.unlink(missing_ok=True)
    return Result(name, "reassembled", detail)


def _verify(skill_dir: Path, spec: CapabilitySpec, prov: dict):
    """All six gates, with the saved differential cases; (report, None) or (None, why it could not run)."""
    from zyven.analysis.analyzer import analyze
    from zyven.compiler.verify import verify
    checkout = prov.get("source_checkout")
    source_root = prov.get("source_root") or "."
    if not checkout:
        return None, "provenance has no source_checkout"
    src = Path(checkout)
    repo = src if source_root in ("", ".") else Path(*src.parts[:len(src.parts) - len(Path(source_root).parts)])
    if not repo.exists():
        return None, f"source checkout {repo} is missing (run zyven sync)"
    a = analyze(repo, source_root=None if source_root in ("", ".") else source_root)
    tests_file = skill_dir / "diff_tests.json"
    diff = None
    if tests_file.exists():  # saved with typed arguments (lists, objects), which the Tester's schema does not allow;
        cases = json.loads(tests_file.read_text(encoding="utf-8")).get("cases") or []  # verify types them again anyway
        diff = DiffTests.model_construct(cases=[DiffCase.model_construct(**c) for c in cases])
    import warnings
    with warnings.catch_warnings():  # pydantic notes that the constructed cases hold lists; expected, see above
        warnings.filterwarnings("ignore", message=".*serializ", category=UserWarning)
        return verify(skill_dir, spec, repo, set(a.packages), diff_tests=diff, source_root=a.source_root,
                      skip_tests=[t.file for t in a.tests if t.third_party]), None


def reassemble(dirs: list[Path], verify_gates: bool = True, dry_run: bool = False) -> list[Result]:
    out = []
    for d in dirs:
        if is_skill(d):
            out.append(reassemble_one(d, verify_gates, dry_run))
        elif d.is_dir():  # a library: every skill inside
            out += [reassemble_one(s, verify_gates, dry_run) for s in sorted(d.iterdir()) if s.is_dir() and is_skill(s)]
        else:
            out.append(Result(d.name, "skipped", "no such folder"))
    return out
