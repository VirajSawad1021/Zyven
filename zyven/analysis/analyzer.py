"""Deterministic Python repository analyzer.

Parses source with `ast` only; repository code is never imported or executed here.
Produces structured evidence (symbols, signatures, imports, call edges, test links,
side-effect hints, public exports) that both the rules-only miner and the model consume.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SKIP_DIRS = {".git", ".venv", "venv", "env", "node_modules", "build", "dist", "__pycache__", ".tox", "docs", "examples"}

# External call prefixes that indicate side effects worth surfacing to a reviewer.
SIDE_EFFECT_PATTERNS = {
    "filesystem": ("open", "os.remove", "os.unlink", "os.rename", "os.makedirs", "os.mkdir", "shutil.", "pathlib.Path.write",
                   "pathlib.Path.unlink", "tempfile."),
    "network": ("requests.", "httpx.", "urllib.request", "urllib3.", "socket.", "aiohttp.", "http.client"),
    "subprocess": ("subprocess.", "os.system", "os.popen", "os.exec"),
    "environment": ("os.environ", "os.getenv", "os.putenv"),
    "database": ("sqlite3.", "psycopg", "pymysql", "sqlalchemy.", "django.db"),
    "time_dependent": ("datetime.datetime.now", "datetime.date.today", "datetime.datetime.today", "time.time",
                       "datetime.datetime.utcnow"),
    "randomness": ("random.", "secrets.", "uuid.uuid4"),
}


_SIDE_EFFECT_BUILTINS = {"open", "exec", "eval", "compile", "__import__", "input"}


@dataclass
class Param:
    name: str
    annotation: str | None = None
    default: str | None = None
    kind: str = "positional_or_keyword"


@dataclass
class Symbol:
    id: str  # "<module>.<qualname>", e.g. nepali.date_converter.NepaliDateConverter.english_to_nepali
    module: str
    qualname: str
    kind: str  # function | class | method
    file: str
    lineno: int
    end_lineno: int
    params: list[Param] = field(default_factory=list)
    returns: str | None = None
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    is_public: bool = True
    calls: list[str] = field(default_factory=list)  # resolved internal symbol ids
    external_calls: list[str] = field(default_factory=list)  # resolved dotted names outside the repo
    side_effects: list[str] = field(default_factory=list)
    tested_by: list[str] = field(default_factory=list)  # test file paths that reference this symbol
    exported_as: list[str] = field(default_factory=list)  # public import paths, e.g. nepali.datetime.nepalidate
    loc: int = 0


@dataclass
class ModuleInfo:
    name: str
    file: str
    docstring: str | None
    imports: dict[str, str]  # local alias -> fully qualified name
    internal_imports: list[str]
    external_imports: list[str]
    instances: dict[str, str]  # module-level name -> class symbol id (e.g. converter -> ...NepaliDateConverter)
    has_main_block: bool
    is_test: bool
    loc: int


@dataclass
class TestFile:
    file: str
    module: str
    test_count: int  # test functions, or doctest examples (">>>" lines) for doctest files/modules
    references: list[str]  # internal symbol ids the tests import or call
    kind: str = "python"  # python | doctest-file | module-doctest
    third_party: list[str] = field(default_factory=list)  # non-stdlib, non-repo imports the tests need


@dataclass
class Analysis:
    repo: str
    commit: str | None
    license: str | None
    packages: list[str]
    modules: list[ModuleInfo]
    symbols: list[Symbol]
    tests: list[TestFile]
    external_dependencies: list[str]
    warnings: list[str]
    source_root: str = "."  # where importable packages live, relative to the repo (".", "src", "python", ...)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git_commit(repo: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _detect_license(repo: Path) -> str | None:
    candidates = sorted(p for p in repo.iterdir() if p.is_file() and p.name.lower().startswith(("licen", "copying")))
    for p in candidates:  # LICENSE, LICENSE.txt, license.txt, COPYING, ...
        if p.exists():
            head = p.read_text(encoding="utf-8", errors="replace")[:600].lower()
            for key, label in (("gnu lesser general public license", "LGPL"), ("mit license", "MIT"), ("permission is hereby granted, free of charge", "MIT"), ("apache license", "Apache-2.0"), ("bsd", "BSD"),
                               ("gnu general public license", "GPL"), ("mozilla public", "MPL-2.0")):
                if key in head:
                    return label
            return "unknown (license file present)"
    return None


_STDLIB = set(sys.stdlib_module_names) | {"__future__"}
_TEST_TOOLS = {"pytest", "_pytest", "hypothesis", "pretend"}  # available in the sandbox image
_NOT_LIBRARY = {"tests", "test", "docs", "doc", "examples", "scripts", "tools", "update", "benchmarks", "build"}


def detect_source_root(repo: Path) -> str:
    """Where the importable packages live: the first of ., src, python, lib holding a real package."""
    for cand in (".", "src", "python", "lib"):
        d = repo / cand
        if not d.is_dir():
            continue
        if any(p.is_dir() and (p / "__init__.py").exists() and p.name not in _NOT_LIBRARY
               and not p.name.startswith((".", "_")) for p in d.iterdir()):
            return cand
    return "."


def _module_name(repo: Path, file: Path) -> str:
    rel = file.relative_to(repo).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_test_path(rel: str) -> bool:
    p = Path(rel)
    return "tests" in p.parts or "test" in p.parts or p.name.startswith("test_") or p.name.endswith("_test.py")


def _unparse(node: ast.AST | None) -> str | None:
    return ast.unparse(node) if node is not None else None


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Param]:
    a = fn.args
    out: list[Param] = []
    positional = a.posonlyargs + a.args
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for i, (arg, d) in enumerate(zip(positional, defaults)):
        kind = "positional_only" if i < len(a.posonlyargs) else "positional_or_keyword"
        out.append(Param(arg.arg, _unparse(arg.annotation), _unparse(d), kind))
    if a.vararg:
        out.append(Param("*" + a.vararg.arg, _unparse(a.vararg.annotation), None, "var_positional"))
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        out.append(Param(arg.arg, _unparse(arg.annotation), _unparse(d), "keyword_only"))
    if a.kwarg:
        out.append(Param("**" + a.kwarg.arg, _unparse(a.kwarg.annotation), None, "var_keyword"))
    return out


def _resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    parts = module.split(".")
    base = parts if is_package else parts[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, target] if target else base)


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else None
    return None


class _Collector(ast.NodeVisitor):
    """Collects symbols in one module, with their raw (unresolved) call names."""

    def __init__(self, module: str, file: str) -> None:
        self.module = module
        self.file = file
        self.symbols: list[Symbol] = []
        self.raw_calls: dict[str, list[str]] = defaultdict(list)
        self.stack: list[tuple[str, str]] = []  # (name, kind)

    def _add(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> Symbol:
        qual = ".".join([n for n, _ in self.stack] + [node.name])
        public = not any(part.startswith("_") and not part.startswith("__") for part in qual.split("."))
        sym = Symbol(
            id=f"{self.module}.{qual}" if self.module else qual,
            module=self.module, qualname=qual, kind=kind, file=self.file,
            lineno=node.lineno, end_lineno=node.end_lineno or node.lineno,
            decorators=[ast.unparse(d) for d in node.decorator_list],
            docstring=(ast.get_docstring(node) or None),
            is_public=public,
            loc=(node.end_lineno or node.lineno) - node.lineno + 1,
        )
        if not isinstance(node, ast.ClassDef):
            sym.params = _params(node)
            sym.returns = _unparse(node.returns)
        self.symbols.append(sym)
        return sym

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if any(k == "function" or k == "method" for _, k in self.stack):
            return  # skip classes nested in functions
        self._add(node, "class")
        self.stack.append((node.name, "class"))
        self.generic_visit(node)
        self.stack.pop()

    def _visit_fn(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if any(k in ("function", "method") for _, k in self.stack):
            return  # nested helpers are attributed to their enclosing function
        kind = "method" if self.stack and self.stack[-1][1] == "class" else "function"
        sym = self._add(node, kind)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = _dotted(sub.func)
                if name:
                    self.raw_calls[sym.id].append(name)
            elif isinstance(sub, ast.Attribute) and _dotted(sub) and _dotted(sub).startswith("os.environ"):
                self.raw_calls[sym.id].append("os.environ")

    visit_FunctionDef = _visit_fn
    visit_AsyncFunctionDef = _visit_fn


def analyze(repo_path: str | Path, source_root: str | None = None) -> Analysis:
    repo = Path(repo_path).resolve()
    root = source_root or detect_source_root(repo)
    lib_dir = (repo / root).resolve()
    warnings: list[str] = []
    files = [
        p for p in sorted(repo.rglob("*.py"))
        if not any(part in SKIP_DIRS for part in p.relative_to(repo).parts) and p.name != "setup.py"
        # with a src-style layout, library code comes from the source root; tests may live anywhere
        and (root == "." or p.resolve().is_relative_to(lib_dir) or _is_test_path(p.relative_to(repo).as_posix()))
    ]

    trees: dict[str, tuple[ast.Module, str, bool]] = {}  # module -> (tree, rel file, is_package)
    for f in files:
        rel = f.relative_to(repo).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError as e:
            warnings.append(f"syntax error in {rel}: {e.msg} (line {e.lineno})")
            continue
        base = lib_dir if f.resolve().is_relative_to(lib_dir) else repo
        trees[_module_name(base, f.resolve() if base is lib_dir else f)] = (tree, rel, f.name == "__init__.py")

    internal_roots = {m.split(".")[0] for m in trees}
    packages = sorted({m.split(".")[0] for m, (_, rel, _) in trees.items() if not _is_test_path(rel)})

    def is_internal(fq: str) -> bool:
        return fq.split(".")[0] in internal_roots

    # Pass 1: imports, symbols, raw calls per module.
    modules: dict[str, ModuleInfo] = {}
    collectors: dict[str, _Collector] = {}
    for mod, (tree, rel, is_pkg) in list(trees.items()):
        imports: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_relative(mod, is_pkg, node.level, node.module) if node.level else (node.module or "")
                for a in node.names:
                    if a.name != "*":
                        imports[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
        col = _Collector(mod, rel)
        try:  # generated code (huge literals/expressions) can nest deeper than the interpreter allows
            col.visit(tree)
            loc = len(ast.unparse(tree).splitlines())
        except RecursionError:
            warnings.append(f"skipped {rel}: AST nested too deeply to analyze")
            del trees[mod]
            continue
        collectors[mod] = col
        has_main = any(
            isinstance(n, ast.If) and "__name__" in ast.unparse(n.test) and "__main__" in ast.unparse(n.test)
            for n in tree.body
        )
        internal = sorted({v for v in imports.values() if is_internal(v)})
        external = sorted({v.split(".")[0] for v in imports.values() if not is_internal(v)})
        modules[mod] = ModuleInfo(
            name=mod, file=rel, docstring=ast.get_docstring(tree), imports=imports,
            internal_imports=internal, external_imports=external, instances={},
            has_main_block=has_main, is_test=_is_test_path(rel), loc=loc,
        )

    symbols: dict[str, Symbol] = {s.id: s for c in collectors.values() for s in c.symbols}

    def resolve(fq: str, depth: int = 0) -> str | None:
        """Follow re-exports and module-level instances until fq names a known symbol."""
        if fq in symbols or depth > 6:
            return fq if fq in symbols else None
        parts = fq.split(".")
        for cut in range(len(parts) - 1, 0, -1):
            mod, rest = ".".join(parts[:cut]), parts[cut:]
            info = modules.get(mod)
            if not info:
                continue
            head = rest[0]
            if head in info.instances:  # converter.english_to_nepali -> Class.english_to_nepali
                return resolve(".".join([info.instances[head], *rest[1:]]), depth + 1)
            if head in info.imports and info.imports[head] != fq:  # re-export through __init__
                return resolve(".".join([info.imports[head], *rest[1:]]), depth + 1)
            break
        return None

    # Module-level instances: `converter = NepaliDateConverter()`.
    for mod, (tree, _, _) in trees.items():
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                callee = _dotted(node.value.func)
                if not callee:
                    continue
                head, _, tail = callee.partition(".")
                fq = modules[mod].imports.get(head, f"{mod}.{head}") + (f".{tail}" if tail else "")
                target = resolve(fq)
                if target and symbols[target].kind == "class":
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            modules[mod].instances[t.id] = target

    # Pass 2: resolve calls.
    for mod, col in collectors.items():
        info = modules[mod]
        for sym_id, raw in col.raw_calls.items():
            sym = symbols[sym_id]
            cls_id = sym_id.rsplit(".", 1)[0] if sym.kind == "method" else None
            internal_calls, external_calls = set(), set()
            for name in raw:
                head, _, tail = name.partition(".")
                if head == "self" and cls_id:
                    fq = f"{cls_id}.{tail.split('.')[0]}" if tail else None
                elif head in info.imports:
                    fq = info.imports[head] + (f".{tail}" if tail else "")
                elif head in info.instances:
                    fq = info.instances[head] + (f".{tail}" if tail else "")
                elif f"{mod}.{head}" in symbols:
                    fq = f"{mod}.{name}"
                else:
                    fq = name  # builtin or unresolved local
                if fq is None:
                    continue
                target = resolve(fq) if is_internal(fq) else None
                if target and target != sym_id:
                    internal_calls.add(target)
                    if symbols[target].kind == "class":  # constructor call -> __init__
                        if f"{target}.__init__" in symbols:
                            internal_calls.add(f"{target}.__init__")
                elif not is_internal(fq) and (head in info.imports or fq in _SIDE_EFFECT_BUILTINS):
                    external_calls.add(fq)  # only real imported modules / notable builtins, not local methods
            sym.calls = sorted(internal_calls)
            sym.external_calls = sorted(external_calls)
            sym.side_effects = sorted({
                cat for cat, pats in SIDE_EFFECT_PATTERNS.items()
                for c in external_calls for p in pats if c == p or c.startswith(p if p.endswith(".") else p + ".")
                or c == p.rstrip(".")
            })

    # Public exports: names re-exported via package __init__ / __all__.
    for mod, info in modules.items():
        if info.is_test:
            continue
        for alias, fq in info.imports.items():
            target = resolve(fq) if is_internal(fq) else None
            if target and not alias.startswith("_") and trees[mod][2]:
                symbols[target].exported_as.append(f"{mod}.{alias}")
            elif target is None and alias in info.instances:
                pass
        for name, cls in info.instances.items():
            if not name.startswith("_"):
                symbols[cls].exported_as.append(f"{mod}.{name} (instance)")

    # Tests: which internal symbols each test file references.
    tests: list[TestFile] = []
    for mod, info in modules.items():
        if not info.is_test:
            continue
        refs: set[str] = set()
        for fq in info.imports.values():
            if is_internal(fq) and (t := resolve(fq)):
                refs.add(t)
        for s in collectors[mod].symbols:
            refs.update(c for c in symbols[s.id].calls if not modules[symbols[c].module].is_test)
        refs = {r for r in refs if not modules[symbols[r].module].is_test}
        # A reference to a class covers its methods that the tests call through instances.
        test_count = sum(1 for s in collectors[mod].symbols if s.qualname.split(".")[-1].startswith("test"))
        needs = sorted({e for e in info.external_imports if e not in _STDLIB and e not in _TEST_TOOLS})
        tests.append(TestFile(file=info.file, module=mod, test_count=test_count, references=sorted(refs),
                              third_party=needs))
        for r in refs:
            symbols[r].tested_by.append(info.file)

    # Doctest files (tests/*.doctest): references come from their `>>> import` lines.
    def module_symbols(mod_name: str) -> list[str]:
        return [sid for sid, s in symbols.items() if s.module == mod_name and s.is_public and s.kind != "method"]

    for f in sorted(repo.rglob("*.doctest")):
        rel = f.relative_to(repo).as_posix()
        if any(part in SKIP_DIRS for part in f.relative_to(repo).parts):
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        examples = [ln.strip()[4:] for ln in lines if ln.strip().startswith(">>> ")]
        refs: set[str] = set()
        for code in examples:
            if not code.startswith(("import ", "from ")):
                continue
            try:
                node = ast.parse(code).body[0]
            except SyntaxError:
                continue
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [f"{node.module}.{a.name}" for a in node.names] if isinstance(node, ast.ImportFrom) else [])
            for fq in names:
                if not is_internal(fq):
                    continue
                if fq in modules:  # imported a module: it tests that module's public API
                    refs.update(module_symbols(fq))
                elif t := resolve(fq):
                    refs.add(t)
        if refs or examples:
            tests.append(TestFile(file=rel, module=rel, test_count=len(examples), references=sorted(refs),
                                  kind="doctest-file"))
            for r in refs:
                symbols[r].tested_by.append(rel)

    # Docstring examples inside source modules are tests too (run with pytest --doctest-modules).
    for mod, (tree, rel, _) in trees.items():
        if modules[mod].is_test:
            continue
        count = sum((ast.get_docstring(n) or "").count(">>> ")
                    for n in [tree, *[x for x in ast.walk(tree)
                                      if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]])
        if count:
            refs = module_symbols(mod)
            tests.append(TestFile(file=rel, module=mod, test_count=count, references=sorted(refs), kind="module-doctest"))
            for r in refs:
                symbols[r].tested_by.append(rel)

    # Methods called via attribute access on instances are hard to see statically; credit tests that
    # reference a class or an exported instance to that class's public methods as weaker evidence.
    for tf in tests:
        for r in list(tf.references):
            if symbols[r].kind == "class":
                for sid, s in symbols.items():
                    if s.kind == "method" and sid.startswith(r + ".") and tf.file not in s.tested_by:
                        s.tested_by.append(tf.file)

    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    ext = sorted({e for m in modules.values() if not m.is_test for e in m.external_imports} - stdlib)
    return Analysis(
        repo=str(repo), commit=_git_commit(repo), license=_detect_license(repo), packages=packages,
        modules=list(modules.values()), symbols=list(symbols.values()), tests=tests,
        external_dependencies=ext, warnings=warnings, source_root=root,
    )
