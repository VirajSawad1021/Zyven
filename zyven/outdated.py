"""`zyven outdated`: which verified skills were built from a library commit that upstream has since moved past.

A skill is verified against one pinned commit. When the library moves on, the skill is still correct for that commit,
but it may now disagree with what users of the current release expect, and fixes upstream do not reach it.

    zyven outdated                     # every skill in the library and skills/
    zyven outdated --fetch             # also: how many commits behind, and do the changes touch modules the skill uses?

Without --fetch only `git ls-remote` is used (network, nothing written). --fetch runs `git fetch` in the skill's pinned
source checkout, which updates remote-tracking refs only; the checked-out commit the skill uses is never changed.
No model is called and nothing is recompiled: re-verifying a moved skill is a deliberate step (compile at the new
commit, then the six gates), because the new upstream code is unreviewed.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Status:
    skill: str
    repository: str
    commit: str
    state: str = "unknown"          # up to date | behind | unknown
    upstream: str = ""
    behind: int | None = None
    touched: list[str] = field(default_factory=list)  # changed files inside the modules the skill uses
    detail: str = ""


def _git(args: list[str], cwd: Path | None = None, timeout: float = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def skill_dirs(paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        if (p / "provenance.json").exists():
            out.append(p)
        elif p.is_dir():
            out += sorted(d for d in p.iterdir() if (d / "provenance.json").exists())
    return list(dict.fromkeys(out))


def _module_files(skill: Path) -> list[str]:
    """Repository paths of the modules the skill's tools are built on (from the spec's included symbols)."""
    try:
        spec = json.loads((skill / "capability.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mods = {s.rsplit(".", 1)[0] for s in spec.get("included_symbols", []) if "." in s}
    return sorted({m.replace(".", "/") for m in mods})


def check(skill: Path, fetch: bool = False) -> Status:
    prov = json.loads((skill / "provenance.json").read_text(encoding="utf-8"))
    st = Status(skill.name, prov.get("repository", ""), str(prov.get("commit", "")))
    if not st.repository.startswith(("http://", "https://", "git@", "file://")):
        st.detail = "provenance has no repository URL"
        return st
    code, out = _git(["ls-remote", st.repository, "HEAD"], timeout=45)
    if code != 0 or not out:
        st.detail = f"git ls-remote failed: {out[:160]}"
        return st
    st.upstream = out.split()[0]
    if st.upstream == st.commit:
        st.state = "up to date"
        return st
    st.state = "behind"
    checkout = Path(prov.get("source_checkout") or "")
    root = prov.get("source_root") or "."
    repo = checkout if root in ("", ".") else Path(*checkout.parts[:len(checkout.parts) - len(Path(root).parts)])
    if not fetch:
        st.detail = "upstream HEAD differs (use --fetch for how far and what changed)"
        return st
    if not (repo / ".git").exists():
        st.detail = f"no local checkout at {repo} to compare in (zyven sync)"
        return st
    code, out = _git(["fetch", "--quiet", "origin", st.upstream], cwd=repo, timeout=300)
    if code != 0:
        st.detail = f"git fetch failed: {out[:160]}"
        return st
    code, out = _git(["rev-list", "--count", f"{st.commit}..{st.upstream}"], cwd=repo)
    st.behind = int(out) if code == 0 and out.isdigit() else None
    code, out = _git(["diff", "--name-only", st.commit, st.upstream], cwd=repo)
    changed = out.splitlines() if code == 0 else []
    prefixes = [(f"{root}/" if root not in ("", ".") else "") + m for m in _module_files(skill)]
    st.touched = sorted(f for f in changed if any(f == p + ".py" or f.startswith(p + "/") or f.startswith(p + ".py")
                                                  for p in prefixes))
    st.detail = (f"{len(changed)} files changed upstream, {len(st.touched)} in modules this skill uses"
                 if changed else "no file changes")
    return st


def to_json(rows: list[Status]) -> str:
    return json.dumps([asdict(r) for r in rows], indent=1)
