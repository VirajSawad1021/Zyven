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
# Names that reach an attribute by a string, which the attribute check above cannot see. `getattr` is allowed only
# as a direct call with a literal, non-dunder name (`getattr(obj, "year", None)`); the others are not needed.
INDIRECT = {"getattr", "attrgetter", "methodcaller"}
FORBIDDEN_NAMES = {"__builtins__", "__loader__", "__spec__"}


def _plain_getattr(call: ast.Call) -> bool:
    """`getattr(x, "name"[, default])` with a literal name that is not a dunder or a forbidden attribute."""
    if len(call.args) not in (2, 3) or call.keywords:
        return False
    name = call.args[1]
    return (isinstance(name, ast.Constant) and isinstance(name.value, str)
            and not name.value.startswith("__") and name.value not in FORBIDDEN_ATTRS)


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
    plain = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "getattr" and _plain_getattr(n)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in INDIRECT and id(node) not in plain:
            v.append(f"line {node.lineno}: '{node.id}' is only allowed as getattr(obj, \"literal_name\")")
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
