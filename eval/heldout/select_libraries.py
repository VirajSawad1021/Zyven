"""Choose the held-out libraries for the compile study by a fixed rule, before any compile is run.

    uv run python eval/heldout/select_libraries.py            # reads the saved snapshots, writes candidates.json
    uv run python eval/heldout/select_libraries.py --fetch    # re-fetches PyPI metadata (results can drift)

The rule (PROTOCOL.md section 2) has an automatic part, applied here, and a reviewed part, recorded with a reason per
package in review.json. The PyPI metadata snapshot (about 7 MB) is not committed; candidates.json records the outcome
for every one of the 3000 projects, so the selection can be checked without it, and --fetch re-derives it (metadata
can change after 2026-11-16, when it was fetched).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

HERE = Path(__file__).parent
RANKING = HERE / "top-pypi-packages-2026-11-01.json"  # hugovk/top-pypi-packages, 30-day downloads, 2026-11-01
METADATA = HERE / "pypi-metadata-snapshot.json"
OUT = HERE / "candidates.json"
TOP_N = 3000  # how far down the download ranking to look

# Libraries Zyven was developed or evaluated against, and ones proposed for its catalog: never held out.
SEEN = {"python-stdnum", "nepali", "hijridate", "pyluach", "phonenumbers", "phonenumberslite", "sympy", "packaging",
        "networkx", "sqlglot", "mpmath"}  # mpmath: sympy's arithmetic, used in the sympy compile attempts

ALLOWED_TOPICS = (  # computational domains where a library's answer is the ground truth
    "Topic :: Scientific/Engineering",
    "Topic :: Text Processing",
    "Topic :: Office/Business",
    "Topic :: Software Development :: Localization",
    "Topic :: Software Development :: Internationalization",
)
EXCLUDED_TOPICS = (  # services, systems and tooling: no pure input -> output answer to compare
    "Topic :: Internet", "Topic :: System", "Topic :: Database", "Topic :: Communications",
    "Topic :: Software Development :: Build Tools", "Topic :: Software Development :: Testing",
    "Topic :: Software Development :: Code Generators", "Topic :: Software Development :: Debuggers",
    "Topic :: Multimedia", "Topic :: Desktop Environment", "Topic :: Security",
)
EXCLUDED_PREFIXES = ("types-", "pytest-", "flake8-", "sphinx", "mkdocs", "jupyter", "django", "flask", "azure-",
                     "google-", "aws", "opentelemetry", "pydantic")
HEAVY = {"numpy", "scipy", "pandas", "torch", "tensorflow", "jax", "scikit-learn", "matplotlib", "pyarrow", "polars"}


def _req_names(reqs: list[str] | None) -> set[str]:
    out = set()
    for r in reqs or []:
        if "extra ==" in r:  # optional extras do not count
            continue
        name = r.split(";")[0].strip()
        for sep in "<>=!~[ (":
            name = name.split(sep)[0]
        out.add(name.lower().replace("_", "-"))
    return out


def automatic_rule(project: str, meta: dict | None) -> str | None:
    """None if the package passes the automatic rule, else the reason it does not."""
    if project in SEEN:
        return "A1 seen in development"
    if project.startswith(EXCLUDED_PREFIXES):
        return "A2 plugin, framework or cloud SDK by name"
    if not meta:
        return "A3 no PyPI metadata"
    info = meta["info"]
    classifiers = info.get("classifiers") or []
    if not any(c.startswith(ALLOWED_TOPICS) for c in classifiers):
        return "A4 no computational topic classifier"
    if any(c.startswith(EXCLUDED_TOPICS) for c in classifiers):
        return "A5 service, system or tooling topic"
    if not any(f["filename"].endswith("-none-any.whl") and f["packagetype"] == "bdist_wheel"
               for f in meta.get("urls") or []):
        return "A6 no pure-Python wheel for the latest release"
    heavy = _req_names(info.get("requires_dist")) & HEAVY
    if heavy:
        return f"A7 requires {sorted(heavy)}"
    if not (info.get("license") or info.get("license_expression")
            or any(c.startswith("License ::") for c in classifiers)):
        return "A8 no license stated"
    return None


async def fetch(projects: list[str]) -> dict[str, dict | None]:
    import httpx
    sem = asyncio.Semaphore(16)
    out: dict[str, dict | None] = {}

    async def one(client, p):
        async with sem:
            try:
                r = await client.get(f"https://pypi.org/pypi/{p}/json", timeout=30)
                d = r.json() if r.status_code == 200 else None
            except (httpx.HTTPError, ValueError):
                d = None
        if d:  # keep only what the rule reads, so the snapshot stays small
            d = {"info": {k: d["info"].get(k) for k in ("name", "version", "summary", "classifiers",
                                                        "requires_dist", "license", "license_expression",
                                                        "project_urls", "home_page")},
                 "urls": [{"filename": u["filename"], "packagetype": u["packagetype"]} for u in d.get("urls", [])]}
        out[p] = d

    async with httpx.AsyncClient(headers={"User-Agent": "zyven-heldout-selection"}) as client:
        await asyncio.gather(*(one(client, p) for p in projects))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="re-fetch PyPI metadata instead of using the snapshot")
    args = ap.parse_args()
    rows = json.loads(RANKING.read_text(encoding="utf-8"))["rows"][:TOP_N]
    projects = [r["project"] for r in rows]
    if args.fetch or not METADATA.exists():
        meta = asyncio.run(fetch(projects))
        METADATA.write_text(json.dumps(meta, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    passed, reasons, outcomes = [], {}, {}
    for rank, r in enumerate(rows, 1):
        why = automatic_rule(r["project"], meta.get(r["project"]))
        outcomes[r["project"]] = why or "candidate"
        if why:
            reasons[why.split(" ")[0]] = reasons.get(why.split(" ")[0], 0) + 1
            continue
        info = meta[r["project"]]["info"]
        passed.append({"rank": rank, "project": r["project"], "downloads_30d": r["download_count"],
                       "version": info["version"], "summary": info.get("summary") or ""})
    OUT.write_text(json.dumps({"ranking": RANKING.name, "top_n": TOP_N, "excluded_by_rule": dict(sorted(reasons.items())),
                               "metadata_fetched": "2026-11-16", "candidates": passed,
                               "outcome_by_project": outcomes}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(passed)} candidates from the top {TOP_N}; excluded: {dict(sorted(reasons.items()))}")


if __name__ == "__main__":
    main()
