"""Differential tests, executed INSIDE the sandbox container.

Usage: python /opt/zyven/diff_check.py /skill/server.py /skill/diff_tests.json
       python /opt/zyven/diff_check.py --references /skill/references.json   (references only, no tool)
For each case: evaluate the Tester's library reference expression, call the tool function directly with
the case args, and compare the tool's output field to the reference value. Prints one JSON report.

Generated cases. A reference written with {arg} placeholders is a template: the same program gives the library's
answer for any arguments. After the Tester's own cases, each tool gets up to GENERATED_PER_TOOL more argument sets,
mixed from the values its cases use and small variations of them (numbers +-1, 0 and negated; text with changed case,
a character dropped, reversed; lists shortened, reversed or emptied). Case and spacing are not varied: gate 4 already
requires tools to treat those as the same input. The library decides each one: if it rejects the input, the case is
inconclusive. If it gives an answer, a tool that returns a different one fails. A tool that declines the input (it
raises, or answers with an error message or a validity flag set to False) is recorded but not counted, because
rejecting some input on purpose is allowed (gate 5), and a Tester's reference is often written for valid input only
(python-stdnum's format() will format an invalid ISBN). A case that compares the validity flag itself is still scored. The draw is seeded, so a rerun checks the
same inputs. No model is involved.
"""

import ast
import json
import random
import runpy
import sys
import traceback

GENERATED_PER_TOOL = 12
SEED = 20261118


def _norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    s = str(v).strip()
    try:
        return float(s) if s and s.lstrip("-").replace(".", "", 1).isdigit() and not s.startswith("0") else s
    except ValueError:
        return s


def evaluate(source: str, env: dict):
    """The reference is a short program: run its setup statements, then evaluate its last line (an expression)."""
    body = ast.parse(source).body
    if not body or not isinstance(body[-1], ast.Expr):
        raise ValueError("the reference must end with an expression")
    exec(compile(ast.Module(body=body[:-1], type_ignores=[]), "<reference>", "exec"), env)  # noqa: S102 - policy-checked
    return eval(compile(ast.Expression(body[-1].value), "<reference>", "eval"), env)  # noqa: S307 - policy-checked


def _variations(v) -> list:
    """Small changes of one argument value, keeping its type."""
    if isinstance(v, bool):  # before int: bool is a subclass of int
        return [not v]
    if isinstance(v, int):
        return [v - 1, v + 1, 0, -v, v * 10]
    if isinstance(v, float):
        return [v / 2, -v, 0.0, v + 1]
    if isinstance(v, str):  # changes of meaning only: case and spacing are gate 4's job (the same input there)
        return [v[:-1], v[1:], v[::-1]] if len(v) > 1 else []
    if isinstance(v, list):
        return [v[:-1], v[::-1], [], v + v[:1]] if v else []
    return []


def generated_args(tool_cases: list, n: int, rng: random.Random) -> list:
    """Up to n new argument sets for one tool: each argument drawn from the values its cases use and their variations."""
    keys = list(tool_cases[0]["args"])
    tool_cases = [c for c in tool_cases if list(c["args"]) == keys]  # mix only cases with the same parameters
    pools = {}
    for k in keys:
        pool = []
        for c in tool_cases:
            for x in [c["args"][k]] + _variations(c["args"][k]):
                if not any(x == y and type(x) is type(y) for y in pool):  # True == 1 == 1.0, but not the same input
                    pool.append(x)
        pools[k] = pool
    seen = [c["args"] for c in tool_cases]
    out: list = []
    for _ in range(n * 8):  # bounded: small pools simply give fewer sets
        args = {k: rng.choice(pools[k]) for k in keys}
        if args not in seen and args not in out:
            out.append(args)
        if len(out) == n:
            break
    return out


def _templated(c: dict) -> bool:
    """The reference uses every argument through a placeholder, so it is valid for any arguments."""
    return bool(c["args"]) and all("{" + k + "}" in c["reference_expr"] for k in c["args"])


FLAGS = ("is_valid", "valid", "success", "ok")


def _declined(out, field: str) -> bool:
    """The tool answered "this input is not valid" (an error message, or a validity flag set to False) instead of a
    result. Not when the compared field is that flag itself: then a wrong verdict is exactly what must be caught."""
    if not isinstance(out, dict) or field == "error" or field in FLAGS:
        return False
    return bool(out.get("error")) or any(out.get(f) is False for f in FLAGS)


def filled(c: dict, args: dict) -> str:
    """The reference program with its {arg} placeholders replaced by the case's argument values."""
    expr = c["reference_expr"]
    for k, v in args.items():  # {arg} placeholders: the reference uses exactly the tool's inputs
        for quoted in ("'{" + k + "}'", '"{' + k + '}"'):  # placeholder written inside quotes
            expr = expr.replace(quoted, repr(v))
        expr = expr.replace("{" + k + "}", repr(v))
    return expr


def reference_value(c: dict, args: dict):
    """What the library itself gives for this case: run the reference program's imports and setup, then its last line.
    Raises whatever the library raises."""
    env: dict = {}
    for line in c.get("reference_imports", []):
        exec(line, env)  # noqa: S102 - imports were policy-checked by the harness before the container ran
    return evaluate(filled(c, args), env)  # policy-checked by the harness, run sandboxed


def _check(ns: dict, c: dict, args: dict) -> dict:
    r = {"tool": c["tool"], "args": args, "field": c["field"], "expr": filled(c, args)}
    try:
        expected = reference_value(c, args)
    except Exception as e:  # noqa: BLE001
        r.update(status="invalid_reference", detail=repr(e)[:300])
        return r
    try:
        out = ns[c["tool"]](**args)
        got = out.get(c["field"]) if isinstance(out, dict) else out
        r.update(expected=expected if isinstance(expected, (str, int, float, bool, type(None))) else str(expected),
                 got=got if isinstance(got, (str, int, float, bool, type(None))) else str(got))
        r["status"] = "match" if _norm(got) == _norm(expected) else "mismatch"
        r["tool_declined"] = _declined(out, c["field"])
    except Exception:  # noqa: BLE001
        r.update(status="tool_error", detail="".join(traceback.format_exc().splitlines(keepends=True)[-6:]))
    return r


def main(server_path: str, tests_path: str, generated_per_tool: int | None = None) -> dict:
    saved = json.load(open(tests_path, encoding="utf-8"))
    cases = saved["cases"]
    if generated_per_tool is None:  # an experiment may set it in the file; 0 turns generated cases off
        generated_per_tool = saved.get("generated_per_tool", GENERATED_PER_TOOL)
    ns = runpy.run_path(server_path, run_name="zyven_diff")
    results = [_check(ns, c, c["args"]) for c in cases]
    # generated cases: only from templated references that worked on the Tester's own arguments
    rng = random.Random(SEED)
    usable = [c for c, r in zip(cases, results) if r["status"] != "invalid_reference" and _templated(c)]
    for tool in dict.fromkeys(c["tool"] for c in usable):
        tool_cases = [c for c in usable if c["tool"] == tool]
        for i, args in enumerate(generated_args(tool_cases, generated_per_tool, rng)):
            c = tool_cases[i % len(tool_cases)]  # rotate through the tool's references (and fields)
            r = _check(ns, c, args)
            r["generated"] = True
            if r["status"] == "invalid_reference":  # the library itself rejects these arguments
                r["status"] = "inconclusive"
            elif r["status"] == "tool_error" or (r["status"] == "mismatch" and r.get("tool_declined")):
                r["status"] = "tool_rejected"  # the tool refused input the library accepts: recorded, not counted
            results.append(r)
    return {"results": results}


def check_references(tests_path: str) -> dict:
    """Run each case's reference program on its own arguments, with no tool involved: does the library accept it?
    Used right after the Tester answers, so a reference that misuses the library can be sent back before any gate."""
    cases = json.load(open(tests_path, encoding="utf-8"))["cases"]
    out = []
    for c in cases:
        try:
            reference_value(c, c["args"])
            out.append({"ok": True})
        except Exception as e:  # noqa: BLE001
            out.append({"ok": False, "error": repr(e)[:300], "expr": filled(c, c["args"])[:600]})
    return {"references": out}


if __name__ == "__main__":
    try:
        out = check_references(sys.argv[2]) if sys.argv[1] == "--references" else main(sys.argv[1], sys.argv[2])
    except Exception as e:  # noqa: BLE001
        out = {"fatal": repr(e)}
    print("ZYVEN_DIFF_REPORT=" + json.dumps(out, ensure_ascii=False, default=str))
