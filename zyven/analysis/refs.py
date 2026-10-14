"""Map a model-written reference to a real symbol id, deterministically.

Models naturally write public import paths (`nepali.datetime.parser.strptime`) or call paths through
module-level instances (`nepali.date_converter.english_to_nepali` for `converter.english_to_nepali`).
These are resolved against the analysis; anything that cannot be resolved is rejected.
"""

from __future__ import annotations

from zyven.analysis.analyzer import Analysis


class RefResolver:
    def __init__(self, a: Analysis) -> None:
        self.symbols = {s.id: s for s in a.symbols}
        self.modules = {m.name: m for m in a.modules}
        self._by_suffix: dict[str, list[str]] = {}
        for sid in self.symbols:
            parts = sid.split(".")
            for i in range(1, len(parts)):
                self._by_suffix.setdefault(".".join(parts[i:]), []).append(sid)

    def resolve(self, ref: str, depth: int = 0) -> str | None:
        ref = ref.strip().replace(":", ".").replace("/", ".").removesuffix("()")
        if ref in self.symbols:
            return ref
        if depth > 6:
            return None
        parts = ref.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            mod_name, rest = ".".join(parts[:cut]), parts[cut:]
            mod = self.modules.get(mod_name)
            if not mod:
                continue
            head = rest[0]
            if head in mod.instances:  # converter.english_to_nepali
                return self.resolve(".".join([mod.instances[head], *rest[1:]]), depth + 1)
            if head in mod.imports and mod.imports[head] != ref:  # re-export via __init__
                return self.resolve(".".join([mod.imports[head], *rest[1:]]), depth + 1)
            # module.method where the module exposes exactly one instance with that method
            hits = [f"{cls}.{head}" for cls in mod.instances.values() if f"{cls}.{head}" in self.symbols]
            if len(hits) == 1 and len(rest) == 1:
                return hits[0]
            break
        # Unique dotted-suffix match (at least two components, to avoid ambiguous bare names).
        if ref.count(".") >= 1:
            cands = self._by_suffix.get(".".join(parts[-2:]), [])
            if len(cands) == 1:
                return cands[0]
        return None

    def resolve_all(self, refs: list[str]) -> tuple[list[str], list[str]]:
        """Returns (resolved unique ids, unresolved originals)."""
        ok, bad = [], []
        for r in refs:
            rid = self.resolve(r)
            if rid and rid not in ok:
                ok.append(rid)
            elif not rid:
                bad.append(r)
        return ok, bad
