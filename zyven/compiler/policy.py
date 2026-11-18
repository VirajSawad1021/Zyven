"""Static policy gate for generated adapter code (runs before any execution).

Wrap-mode adapters may only import the source package and a small allowlist of pure stdlib
modules, and may not use dynamic execution, I/O, process, or introspection escape hatches.

This gate is a filter, not the security boundary: Python has more ways to reach an attribute than a list can name.
The boundary is the container the code then runs in (no network, non-root, read-only, capabilities dropped).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

SAFE_STDLIB = {
    "datetime", "re", "math", "decimal", "fractions", "json", "typing", "enum", "functools", "itertools",
    "collections", "calendar", "string", "dataclasses", "statistics", "unicodedata", "__future__",
}
FRAMEWORK = {"mcp", "pydantic"}  # imported by the harness-written header (server, annotations, parameter docs)
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "input",
                   "breakpoint", "setattr", "delattr"}
FORBIDDEN_ATTRS = {"__subclasses__", "__globals__", "__builtins__", "__code__", "__class__", "__bases__",
                   "__mro__", "__dict__", "system", "popen"}
# Names that reach an attribute by a string, which the attribute check above cannot see. `getattr` is allowed only as
# a direct call, either with a literal, non-dunder name (`getattr(obj, "year", None)`), or as a lookup inside the
# wrapped library (`getattr(phonenumbers.PhoneNumberFormat, fmt)`, the usual way to turn "E164" into a constant).
# The object must then be a name inside a source package, never the module itself or a local value, so the string
# cannot reach a function's globals or a module's loader. The others are not needed.
INDIRECT = {"getattr", "attrgetter", "methodcaller"}
FORBIDDEN_NAMES = {"__builtins__", "__loader__", "__spec__"}


def _plain_getattr(call: ast.Call, modules: set[str] = frozenset(), members: set[str] = frozenset()) -> bool:
    """`getattr(x, "name"[, default])` with a literal name that is not a dunder or a forbidden attribute, or
    `getattr(pkg.Thing, name)` / `getattr(Thing, name)` where Thing comes from a source package."""
    if len(call.args) not in (2, 3) or call.keywords:
        return False
    obj, name = call.args[0], call.args[1]
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return not name.value.startswith("__") and name.value not in FORBIDDEN_ATTRS
    return _library_member(obj, modules, members)


def _library_member(node: ast.AST, modules: set[str], members: set[str]) -> bool:
    """`pkg.A` or `pkg.A.B` (pkg bound by `import pkg [as p]`), or a name from `from pkg import A`."""
    if isinstance(node, ast.Name):
        return node.id in members
    parts = []
    while isinstance(node, ast.Attribute):
        if node.attr.startswith("__"):
            return False
        parts.append(node.attr)
        node = node.value
    return isinstance(node, ast.Name) and node.id in modules and bool(parts)


def _library_names(tree: ast.AST, packages: set[str]) -> tuple[set[str], set[str]]:
    """Names bound to source-package modules, and names imported from them."""
    modules, members = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in packages:
                    modules.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and not node.level and (node.module or "").split(".")[0] in packages:
            members |= {a.asname or a.name for a in node.names if a.name != "*"}
    return modules, members


@dataclass
class PolicyReport:
    ok: bool
    violations: list[str] = field(default_factory=list)


def check_adapter(source: str, allowed_packages: set[str]) -> PolicyReport:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return PolicyReport(False, [f"syntax error line {e.lineno}: {e.msg}"])
    allowed = SAFE_STDLIB | FRAMEWORK | allowed_packages
    v: list[str] = []
    modules, members = _library_names(tree, allowed_packages)
    plain = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "getattr" and _plain_getattr(n, modules, members)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in INDIRECT and id(node) not in plain:
            v.append(f"line {node.lineno}: '{node.id}' is only allowed as getattr(obj, \"literal_name\") or as a "
                     "lookup inside the source package, getattr(pkg.Thing, name)")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            v.append(f"line {node.lineno}: name '{node.id}' is not allowed")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in allowed:
                    v.append(f"line {node.lineno}: import of '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level or root not in allowed:
                v.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            v.append(f"line {node.lineno}: call to '{node.func.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            v.append(f"line {node.lineno}: attribute '{node.attr}' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            v.append(f"line {node.lineno}: global/nonlocal is not allowed")
    return PolicyReport(not v, v)
