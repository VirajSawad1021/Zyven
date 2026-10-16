"""Repo explorer: turns a static Analysis into a funnel ("how much of this repo could become MCP tools?")
and a pruned module dependency graph for the board.

Everything here is derived deterministically from the AST analysis; nothing is executed. "MCP-able" is a
heuristic estimate (public, side-effect-free callable with a simple signature), not a guarantee: only the
compile pipeline's gates decide what is actually verified.
"""

from __future__ import annotations

import re
from collections import defaultdict

from zyven.analysis.analyzer import Analysis, Symbol

SIMPLE_TYPES = {
    "str", "int", "float", "bool", "bytes", "complex", "list", "dict", "tuple", "set", "frozenset", "none",
    "optional", "union", "any", "sequence", "mapping", "iterable", "decimal", "literal", "date", "datetime",
    "list", "dict", "tuple", "set", "number", "pathlike",
}
MAX_GRAPH_NODES = 60
TOP_FUNCTIONS = 14


def _simple_annotation(ann: str | None) -> bool:
    if ann is None:
        return True  # unannotated: not disqualifying, the Architect infers the type from docs/tests
    text = re.sub(r"(['\"]).*?\1", "", ann)  # drop string literals (Literal["a", "b"])
    names = re.findall(r"[A-Za-z_][\w.]*", text)
    return all(n.split(".")[-1].lower() in SIMPLE_TYPES for n in names)


def _simple_signature(s: Symbol) -> bool:
    for p in s.params:
        if p.name in ("self", "cls"):
            continue
        if not _simple_annotation(p.annotation):
            return False
    return _simple_annotation(s.returns)


def _module_of(fq: str, module_names: set[str]) -> str | None:
    parts = fq.split(".")
    for i in range(len(parts), 0, -1):
        m = ".".join(parts[:i])
        if m in module_names:
            return m
    return None


def explore(a: Analysis, capabilities: list[dict] | None = None) -> dict:
    """capabilities: [{"name", "title", "entry_points": [symbol ids]}] from the catalog (curated + scouted)."""
    capabilities = capabilities or []
    test_modules = {m.name for m in a.modules if m.is_test}
    src = [s for s in a.symbols if s.module not in test_modules]

    public = [s for s in src if s.is_public and not s.qualname.split(".")[-1].startswith("_")]
    callables = [s for s in public if s.kind in ("function", "method")]
    pure = [s for s in callables if not s.side_effects]
    mcp_able = [s for s in pure if _simple_signature(s)]
    # methods need an instance first, so the cleanest direct candidates are module-level functions
    direct = [s for s in mcp_able if s.kind == "function"]
    tested = [s for s in mcp_able if s.tested_by]

    by_id = {s.id: s for s in src}
    entry_to_cap: dict[str, str] = {}
    for c in capabilities:
        for ep in c.get("entry_points", []):
            entry_to_cap.setdefault(ep, c["name"])
    covered = [s for s in mcp_able if s.id in entry_to_cap]
    covered_any = [ep for ep in entry_to_cap if ep in by_id]

    funnel = [
        {"stage": "Symbols in source modules", "count": len(src), "note": "functions, classes and methods outside tests"},
        {"stage": "Public", "count": len(public), "note": "no leading underscore, in a public module"},
        {"stage": "Public callables", "count": len(callables), "note": "functions and methods (classes excluded)"},
        {"stage": "Side-effect free", "count": len(pure), "note": "no file, network, process or env access found"},
        {"stage": "MCP-able (estimate)", "count": len(mcp_able), "note": "simple, JSON-friendly signature"},
        {"stage": "...with upstream tests", "count": len(tested), "note": "a test file references the symbol"},
        {"stage": "In a catalog capability", "count": len(covered), "note": "entry point of a curated or scouted capability"},
    ]

    # --- module graph -------------------------------------------------------------------------------
    mods = {m.name: m for m in a.modules if not m.is_test}
    names = set(mods)
    sym_count: dict[str, int] = defaultdict(int)
    mcp_count: dict[str, int] = defaultdict(int)
    cap_of: dict[str, str] = {}
    for s in src:
        sym_count[s.module] += 1
    for s in mcp_able:
        mcp_count[s.module] += 1
    for ep, cap in entry_to_cap.items():
        if ep in by_id:
            cap_of.setdefault(by_id[ep].module, cap)

    edges_all: dict[tuple[str, str], int] = defaultdict(int)
    degree: dict[str, int] = defaultdict(int)
    for m in mods.values():
        for imp in m.internal_imports:
            t = _module_of(imp, names)
            if t and t != m.name:
                edges_all[(m.name, t)] += 1
                degree[m.name] += 1
                degree[t] += 1

    ranked = sorted(names, key=lambda n: (n in cap_of, mcp_count[n] + 2 * degree[n]), reverse=True)
    keep = set(ranked[:MAX_GRAPH_NODES]) | set(cap_of)
    keep = {n for n in keep if sym_count[n] or n in cap_of}
    nodes = [{"id": n, "loc": mods[n].loc, "symbols": sym_count[n], "mcp_able": mcp_count[n],
              "capability": cap_of.get(n)} for n in sorted(keep)]
    edges = [{"source": s, "target": t, "weight": w} for (s, t), w in edges_all.items() if s in keep and t in keep]

    # --- best direct candidates ---------------------------------------------------------------------
    def rank(s: Symbol):
        return (bool(s.tested_by), bool(s.docstring), -len([p for p in s.params if p.name not in ("self", "cls")]), -s.loc)

    top = sorted(direct, key=rank, reverse=True)[:TOP_FUNCTIONS]
    top_out = [{"id": s.id, "params": [p.name for p in s.params if p.name not in ("self", "cls")],
                "returns": s.returns, "tested": bool(s.tested_by), "capability": entry_to_cap.get(s.id),
                "doc": (s.docstring or "").strip().splitlines()[0][:110] if s.docstring else ""} for s in top]

    return {
        "repo": a.repo, "commit": a.commit, "license": a.license, "source_root": a.source_root,
        "totals": {"modules": len(mods), "test_files": len(a.tests), "tests": sum(t.test_count for t in a.tests),
                   "classes": sum(1 for s in src if s.kind == "class"),
                   "external_dependencies": a.external_dependencies, "loc": sum(m.loc for m in mods.values())},
        "funnel": funnel,
        "capabilities": [{"name": c["name"], "title": c.get("title", c["name"]),
                          "entry_points": len([e for e in c.get("entry_points", []) if e in by_id])}
                         for c in capabilities],
        "capability_entry_points_found": len(covered_any),
        "graph": {"nodes": nodes, "edges": edges, "total_modules": len(mods), "shown": len(nodes)},
        "top_candidates": top_out,
        "warnings": a.warnings[:8],
    }
