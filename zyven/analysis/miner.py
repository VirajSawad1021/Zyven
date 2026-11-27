"""Rules-only capability miner (the deterministic baseline) and compact repo digests for the model.

No model is involved here. The AI roles receive `repo_digest()` / `evidence_packet()` output,
and their proposals are compared against `baseline_candidates()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from zyven.analysis.analyzer import Analysis, Symbol

RISKY_EFFECTS = {"network", "subprocess", "database", "filesystem"}


@dataclass
class BaselineCandidate:
    module: str
    entry_points: list[str]
    score: float
    reasons: list[str] = field(default_factory=list)


def _first_line(doc: str | None) -> str:
    lines = (doc or "").strip().splitlines()  # a docstring of only whitespace (sympy has some) has no first line
    return lines[0][:140] if lines else ""


_SECTION = re.compile(r"^[A-Z][A-Za-z ]*:?$")  # a docstring section heading: "Parameters", "Raises:", ...


def documented_return(doc: str | None) -> str:
    """What a docstring says a function returns, as "<type>: <first line>" (or either part), or "".

    For functions without a return annotation: pyluach's festival() is documented as returning "str or None", the
    name or None on other days. Gemma 4 E4B read it as an object (`festival(d).festival_name`) and every such
    reference failed. Reads the NumPy ("Returns" over a dashed line), Google ("Returns:") and reST (":returns:",
    ":rtype:") styles, and a plain sentence that starts with "Returns a ..." (phonenumbers)."""
    import inspect

    lines = inspect.cleandoc(doc or "").splitlines()
    rtype = next((ln.split(":rtype:", 1)[1].strip() for ln in lines if ln.strip().startswith(":rtype:")), "")
    rdesc = next((ln.split(":", 2)[2].strip() for ln in lines if re.match(r"\s*:returns?:", ln)), "")
    for i, ln in enumerate(lines):
        head = ln.strip()
        if head not in ("Returns", "Returns:", "Return", "Return:"):
            continue
        body = lines[i + 1:]
        if body and set(body[0].strip()) == {"-"}:  # NumPy: the type on its own line, the text indented below it
            body = body[1:]
            kind = body[0].strip() if body else ""
            text = []
            for more in body[1:]:  # the description: indented lines up to a blank or unindented one
                if not more.strip() or not more.startswith((" ", "\t")):
                    break
                text.append(more.strip())
            rtype, rdesc = kind, " ".join(text)
        elif body and body[0].strip() and not _SECTION.match(body[0].strip()):  # Google: "str: text" or just text
            first = body[0].strip()
            kind, sep, text = first.partition(":")
            if sep and len(kind) <= 40 and " " not in kind.replace(" or ", "_").replace(", ", "_"):
                rtype, rdesc = kind.strip(), text.strip()
            else:
                rdesc = first
        break
    if not rtype and not rdesc:  # a sentence: "Returns a boolean that indicates ..." (phonenumbers)
        rdesc = next((re.sub(r"^Returns?\s+", "", ln.strip()) for ln in lines if re.match(r"\s*Returns? [a-z`]", ln)),
                     "")
    out = ": ".join(x for x in (rtype, rdesc.replace("``", "`")) if x)
    return out[:160]


def signature(sym: Symbol) -> str:
    params = []
    for p in sym.params:
        if p.name in ("self", "cls"):
            continue
        s = p.name + (f": {p.annotation}" if p.annotation else "") + (f" = {p.default}" if p.default else "")
        params.append(s)
    ret = f" -> {sym.returns}" if sym.returns else ""
    return f"{sym.qualname.split('.')[-1]}({', '.join(params)}){ret}"


def _index(a: Analysis) -> tuple[dict[str, Symbol], dict[str, object]]:
    return {s.id: s for s in a.symbols}, {m.name: m for m in a.modules}


def _is_api_module(mod) -> bool:
    return not mod.is_test


def public_api(a: Analysis) -> list[Symbol]:
    """Public, non-test functions and classes (methods are reached through their class)."""
    syms, mods = _index(a)
    out = []
    for s in a.symbols:
        mod = mods[s.module]
        if mod.is_test or not s.is_public or s.kind == "method":
            continue
        # Private module (`_datetime`) is fine if the symbol is re-exported publicly.
        private_module = any(p.startswith("_") for p in s.module.split("."))
        if private_module and not s.exported_as:
            continue
        out.append(s)
    return out


def score_symbol(sym: Symbol, a: Analysis) -> tuple[float, list[str]]:
    syms, mods = _index(a)
    score, why = 0.0, []
    if sym.exported_as:
        score += 2; why.append("re-exported as public API")
    if sym.tested_by:
        score += 2; why.append(f"covered by {len(sym.tested_by)} test file(s)")
    if sym.docstring:
        score += 1; why.append("documented")
    if sym.params and all(p.annotation for p in sym.params if p.name not in ("self", "cls")):
        score += 0.5; why.append("type-annotated")
    risky = RISKY_EFFECTS & set(sym.side_effects)
    if risky:
        score -= 3; why.append(f"side effects: {', '.join(sorted(risky))}")
    ext = mods[sym.module].external_imports
    if "django" in ext:
        score -= 3; why.append("depends on django")
    if sym.kind == "class":
        methods = [s for s in a.symbols if s.kind == "method" and s.id.startswith(sym.id + ".") and s.is_public]
        if methods:
            score += min(len(methods), 5) * 0.2; why.append(f"{len(methods)} public methods")
    return score, why


def baseline_candidates(a: Analysis, top_k: int = 10) -> list[BaselineCandidate]:
    """Deterministic baseline: one candidate per module, entry points = its best-scored public symbols."""
    by_module: dict[str, list[tuple[float, Symbol, list[str]]]] = {}
    for s in public_api(a):
        sc, why = score_symbol(s, a)
        by_module.setdefault(s.module, []).append((sc, s, why))
    out = []
    for mod, items in by_module.items():
        items.sort(key=lambda t: -t[0])
        best = [t for t in items if t[0] > 0][:4]
        if not best:
            continue
        reasons = sorted({r for _, _, why in best for r in why})
        out.append(BaselineCandidate(module=mod, entry_points=[s.id for _, s, _ in best],
                                     score=round(sum(t[0] for t in best) / len(best), 2), reasons=reasons))
    out.sort(key=lambda c: -c.score)
    return out[:top_k]


def repo_digest(a: Analysis, max_chars: int = 48000, fold_min: int = 4) -> str:
    """Compact, model-readable overview of the public API grouped by module."""
    syms, mods = _index(a)
    lines = [f"Repository: {Path(a.repo).name} (commit {str(a.commit)[:7]}, license {a.license})",
             f"External dependencies: {', '.join(a.external_dependencies) or 'none'}",
             f"Tests: {sum(t.test_count for t in a.tests)} test functions/doctest examples in {len(a.tests)} files", ""]
    api = public_api(a)

    # Fold families of modules that expose the same API (e.g. hundreds of validators with
    # compact/validate/is_valid/format) into one block, so large repos fit in the model's context.
    by_module: dict[str, list[Symbol]] = {}
    for s in api:
        by_module.setdefault(s.module, []).append(s)
    fn_modules = {m: {s.qualname for s in syms_} for m, syms_ in by_module.items()
                  if len(syms_) >= 2 and all(s.kind == "function" for s in syms_) and not mods[m].instances}
    freq: dict[str, int] = {}
    for names in fn_modules.values():
        for n in names:
            freq[n] = freq.get(n, 0) + 1
    common = {n for n, c in freq.items() if c >= max(fold_min, 0.3 * len(fn_modules))}
    need = min(3, len(common))
    members = sorted(m for m, names in fn_modules.items() if common and len(names & common) >= need)
    folded: set[str] = set()
    if len(members) >= fold_min:
        folded.update(members)
        rep_mod = max(members, key=lambda m: (len(fn_modules[m] & common), -len(fn_modules[m])))
        rep = [s for s in by_module[rep_mod] if s.qualname in common]
        tested = sum(1 for m in members if all(s.tested_by for s in by_module[m]))
        effects = sorted({e for m in members for s in by_module[m] for e in s.side_effects})
        lines.append(f"## {len(members)} modules share a common API (symbol id = <module>.<function>, "
                     f"e.g. {rep_mod}.{rep[0].qualname}); {tested}/{len(members)} fully tested"
                     + (f"; some have effects: {', '.join(effects)}" if effects else ""))
        for s in rep:
            lines.append(f"   . {signature(s)}  {_first_line(s.docstring)[:90]}")
        lines.append("   (+name) = extra functions in that module; (-name) = common function it lacks")
        for m in members:
            extra = sorted(fn_modules[m] - common)
            missing = sorted(common - fn_modules[m])
            marks = " ".join([f"+{e}" for e in extra] + [f"-{x}" for x in missing])
            lines.append(f"   - {m} — {_first_line(mods[m].docstring)[:64]}" + (f" ({marks})" if marks else ""))
        lines.append("")

    for mod_name in sorted({s.module for s in api} - folded):
        mod = mods[mod_name]
        lines.append(f"## module {mod_name}  ({mod.file})" + (f" — {_first_line(mod.docstring)}" if mod.docstring else ""))
        if mod.instances:
            lines.append("   instances: " + ", ".join(f"{k} = {v.split('.')[-1]}()" for k, v in mod.instances.items()))
        for s in [x for x in api if x.module == mod_name]:
            tags = []
            if s.tested_by:
                tags.append("tested")
            if s.side_effects:
                tags.append("effects:" + "/".join(s.side_effects))
            if s.exported_as:
                tags.append("exported:" + ",".join(e.split(" ")[0] for e in s.exported_as[:2]))
            tag = f"  [{'; '.join(tags)}]" if tags else ""
            if s.kind == "class":
                methods = [m for m in a.symbols if m.kind == "method" and m.id.startswith(s.id + ".")
                           and m.is_public and not m.qualname.split(".")[-1].startswith("__")]
                lines.append(f" - class {s.id}{tag}  {_first_line(s.docstring)}")
                for m in methods[:12]:
                    lines.append(f"     . {signature(m)}  {_first_line(m.docstring)}")
                if len(methods) > 12:
                    lines.append(f"     . ... {len(methods) - 12} more methods")
            else:
                lines.append(f" - def {s.id}: {signature(s)}{tag}  {_first_line(s.docstring)}")
        lines.append("")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n... [digest truncated]"


def source_of(a: Analysis, sym: Symbol, max_lines: int = 80) -> str:
    if sym.kind == "class":  # class bodies can hold large data tables; methods are shown separately
        doc = f'\n    """{sym.docstring.strip()}"""' if sym.docstring else ""
        return f"class {sym.qualname.split('.')[-1]}:{doc}\n    ...  # {sym.loc} lines; public methods listed below"
    path = Path(a.repo) / sym.file
    src = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = src[sym.lineno - 1: sym.end_lineno]
    if len(body) > max_lines:
        body = body[:max_lines] + [f"    # ... {len(body) - max_lines} more lines"]
    return "\n".join(body)


def test_snippets(a: Analysis, sym: Symbol, max_snippets: int = 6) -> list[str]:
    """Lines from tests that mention the symbol's short name, with a little context."""
    short = sym.qualname.split(".")[-1]
    out: list[str] = []
    for tf in sym.tested_by:
        lines = (Path(a.repo) / tf).read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if short in line and not line.lstrip().startswith(("def ", "#", "import", "from")):
                out.append(f"{tf}:{i + 1}: {line.strip()}")
                if len(out) >= max_snippets:
                    return out
    return out


_FACTORY = ("classmethod", "staticmethod")


def _lineage(sym: Symbol, syms: dict[str, Symbol]) -> list[Symbol]:
    """The class, then its internal base classes, nearest first (each once)."""
    out, todo = [], [sym]
    while todo:
        s = todo.pop(0)
        if s in out:
            continue
        out.append(s)
        todo += [syms[b] for b in s.bases if b in syms and syms[b].kind == "class"]
    return out


def _full(sym: Symbol) -> str:
    """A symbol's signature under its full dotted path, e.g. pyluach.dates.GregorianDate.from_pydate(pydate)."""
    return f"{sym.id.rsplit('.', 1)[0]}.{signature(sym)}" if "." in sym.id else signature(sym)


def construction(a: Analysis, cls: Symbol) -> list[str]:
    """How to build one class: its constructor (inherited if need be) and its public factory methods, with one line
    from the upstream tests that calls the constructor."""
    syms = {s.id: s for s in a.symbols}
    line = [cls] + _lineage(cls, syms)[1:]
    init = next((syms[f"{c.id}.__init__"] for c in line if f"{c.id}.__init__" in syms), None)
    if init is not None:
        params = signature(init).split("(", 1)[1].rsplit(")", 1)[0]
        ctor = f"{cls.id}({params})" + ("" if init.id.startswith(cls.id + ".") else
                                        f"  (constructor inherited from {init.id.rsplit('.', 1)[0]})")
    else:
        how = [b for b in cls.bases if b not in syms] + [d for d in cls.decorators if "dataclass" in d]
        ctor = f"{cls.id}(...)  (no __init__ in its source" + (f"; built by {', '.join(how)}" if how else "") + ")"
    out = [ctor]
    seen: set[str] = set()
    for c in line:
        for m in a.symbols:
            short = m.qualname.split(".")[-1]
            if (m.kind == "method" and m.id.rsplit(".", 1)[0] == c.id and not short.startswith("_")
                    and short not in seen and any(d.split(".")[-1] in _FACTORY for d in m.decorators)):
                seen.add(short)
                kind = "classmethod" if any(d.split(".")[-1] == "classmethod" for d in m.decorators) else "staticmethod"
                sig = signature(m)
                if kind == "classmethod" and m.params and m.params[0].name not in ("self", "cls"):  # e.g. `kls`
                    sig = signature(Symbol(**{**m.__dict__, "params": m.params[1:]}))
                out.append(f"{cls.id}.{sig}  ({kind})")
    if any(b.split(".")[-1] in ("ABC", "ABCMeta") for b in cls.bases):
        out[0] += "  (abstract: build one of its subclasses)"
    short = cls.qualname.split(".")[-1]
    calls = [s for s in test_snippets(a, cls, 20)
             if f"{short}(" in s.split(": ", 1)[-1] and not s.split(": ", 1)[-1].startswith(("class ", "def "))]
    if calls:
        out.append(f"called in the library's tests or docs as: {calls[0]}")
    return out


def _is_exception(cls: Symbol, syms: dict[str, Symbol]) -> bool:
    names = [c.qualname.split(".")[-1] for c in _lineage(cls, syms)] + [b.split(".")[-1] for c in _lineage(cls, syms)
                                                                        for b in c.bases if b not in syms]
    return any(n.endswith(("Error", "Exception", "Warning")) for n in names)


def construction_signatures(a: Analysis, symbol_ids: list[str], max_classes: int = 12) -> str:
    """How to build every library object the given symbols work with: the class each symbol is or belongs to, the
    classes it calls one hop away, the classes named in its annotations or docstring, and the public subclasses of
    each of those (a function documented as taking a BaseDate is called with a GregorianDate). Calling the library
    correctly starts here: a small model wrote GregorianDate("2024-09-02") for GregorianDate(year, month, day).
    Private and exception classes are left out: a caller never builds them."""
    syms, mods = _index(a)
    by_short: dict[str, list[str]] = {}
    subclasses: dict[str, list[str]] = {}
    for s in a.symbols:
        if s.kind == "class" and not mods[s.module].is_test:
            by_short.setdefault(s.qualname.split(".")[-1], []).append(s.id)
            for b in s.bases:
                subclasses.setdefault(b, []).append(s.id)
    classes: list[str] = []

    def add(cid: str | None) -> None:
        s = syms.get(cid or "")
        if (s is None or s.kind != "class" or cid in classes or mods[s.module].is_test or not s.is_public
                or s.qualname.startswith("_") or _is_exception(s, syms)):
            return
        classes.append(cid)
        for sub in subclasses.get(cid, []):
            add(sub)

    def owner(sid: str) -> str | None:
        s = syms.get(sid)
        return sid if s and s.kind == "class" else sid.rsplit(".", 1)[0] if s and s.kind == "method" else None

    for sid in symbol_ids:
        s = syms.get(sid)
        if not s:
            continue
        add(owner(sid))
        members = [s] + ([m for m in a.symbols if m.kind == "method" and m.id.startswith(sid + ".") and m.is_public]
                         if s.kind == "class" else [])
        for m in members:
            for c in m.calls:
                add(owner(c))
            text = [p.annotation for p in m.params if p.annotation] + ([m.returns] if m.returns else []) \
                + [m.docstring or ""]
            for name in dict.fromkeys(w for t in text for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t)):
                if len(by_short.get(name, [])) == 1:
                    add(by_short[name][0])
    lines = []
    for cid in classes[:max_classes]:
        first, *rest = construction(a, syms[cid])
        lines += [f"- {first}"] + [f"    {x}" for x in rest]
    if len(classes) > max_classes:
        lines.append(f"- ... {len(classes) - max_classes} more classes (see the evidence below)")
    return "\n".join(lines)


def describe_symbols(a: Analysis, symbol_ids: list[str]) -> list[str]:
    """Exact signatures for the given symbols: how to build a class, a function's or method's parameters (and how to
    build the class a method belongs to)."""
    syms = {s.id: s for s in a.symbols}
    out: list[str] = []
    for sid in dict.fromkeys(symbol_ids):
        s = syms.get(sid)
        if s is None:
            continue
        if s.kind == "class":
            out += construction(a, s)
        else:
            documented = "" if s.returns else documented_return(s.docstring)
            out.append(_full(s) + (f"  (returns {documented})" if documented else ""))
            cls = syms.get(sid.rsplit(".", 1)[0]) if s.kind == "method" else None
            if cls is not None and cls.kind == "class":
                out += construction(a, cls)[:1]
    return list(dict.fromkeys(out))


def evidence_packet(a: Analysis, entry_points: list[str], max_chars: int = 20000) -> str:
    """Detailed evidence for the Architect: source of entry points, 1-hop callees, test usage."""
    syms, mods = _index(a)
    parts: list[str] = []
    seen: set[str] = set()
    for eid in entry_points:
        s = syms.get(eid)
        if not s:
            continue
        targets = [s]
        if s.kind == "class":
            targets += [m for m in a.symbols if m.kind == "method" and m.id.startswith(s.id + ".") and m.is_public]
        for t in targets:
            if t.id in seen:
                continue
            seen.add(t.id)
            mod = mods[t.module]
            parts.append(f"### {t.id}  ({t.file}:{t.lineno})")
            parts.append(f"exported_as: {t.exported_as or 'not re-exported'} | side_effects: {t.side_effects or 'none'}")
            if mod.instances:
                parts.append("module instances: " + ", ".join(f"{k} = {v}()" for k, v in mod.instances.items()))
            parts.append("```python\n" + source_of(a, t, 60 if t is s else 25) + "\n```")
            callees = [syms[c] for c in t.calls if c in syms][:8]
            if callees:
                parts.append("calls: " + "; ".join(f"{c.id} :: {signature(c)}" for c in callees))
            snips = test_snippets(a, t, 4)
            if snips:
                parts.append("test usage:\n" + "\n".join("  " + x for x in snips))
            parts.append("")
    text = "\n".join(parts)
    return text if len(text) <= max_chars else text[:max_chars] + "\n... [evidence truncated]"
