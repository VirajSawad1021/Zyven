"""Static policy gate for generated adapter code (runs before any execution).

Wrap-mode adapters may only import the source package and a small allowlist of pure stdlib
modules, and may not use dynamic execution, I/O, process, or introspection escape hatches.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

SAFE_STDLIB = {
    "datetime", "re", "math", "decimal", "fractions", "json", "typing", "enum", "functools", "itertools",
    "collections", "calendar", "string", "dataclasses", "statistics", "unicodedata", "__future__",
}
FRAMEWORK = {"mcp"}  # imported by the harness-written header only
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "input",
                   "breakpoint", "setattr", "delattr"}
FORBIDDEN_ATTRS = {"__subclasses__", "__globals__", "__builtins__", "__code__", "__class__", "__bases__",
                   "__mro__", "__dict__", "system", "popen"}


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
    for node in ast.walk(tree):
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
