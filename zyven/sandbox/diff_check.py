"""Differential tests, executed INSIDE the sandbox container.

Usage: python /opt/zyven/diff_check.py /skill/server.py /skill/diff_tests.json
For each case: evaluate the Tester's library reference expression, call the tool function directly with
the case args, and compare the tool's output field to the reference value. Prints one JSON report.
"""

import json
import runpy
import sys
import traceback


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


def main(server_path: str, tests_path: str) -> dict:
    cases = json.load(open(tests_path, encoding="utf-8"))["cases"]
    ns = runpy.run_path(server_path, run_name="zyven_diff")
    results = []
    for c in cases:
        r = {"tool": c["tool"], "args": c["args"], "field": c["field"], "expr": c["reference_expr"]}
        try:
            env: dict = {}
            for line in c.get("reference_imports", []):
                exec(line, env)  # imports were policy-checked by the harness before the container ran
            expr = c["reference_expr"]
            for k, v in c["args"].items():  # {arg} placeholders: the reference uses exactly the tool's inputs
                for quoted in ("'{" + k + "}'", '"{' + k + '}"'):  # placeholder written inside quotes
                    expr = expr.replace(quoted, repr(v))
                expr = expr.replace("{" + k + "}", repr(v))
            r["expr"] = expr
            expected = eval(expr, env)  # noqa: S307 - policy-checked, sandboxed
        except Exception as e:  # noqa: BLE001
            r.update(status="invalid_reference", detail=repr(e)[:300])
            results.append(r)
            continue
        try:
            out = ns[c["tool"]](**c["args"])
            got = out.get(c["field"]) if isinstance(out, dict) else out
            r.update(expected=expected if isinstance(expected, (str, int, float, bool, type(None))) else str(expected),
                     got=got if isinstance(got, (str, int, float, bool, type(None))) else str(got))
            r["status"] = "match" if _norm(got) == _norm(expected) else "mismatch"
        except Exception:  # noqa: BLE001
            r.update(status="tool_error", detail="".join(traceback.format_exc().splitlines(keepends=True)[-6:]))
        results.append(r)
    return {"results": results}


if __name__ == "__main__":
    try:
        out = main(sys.argv[1], sys.argv[2])
    except Exception as e:  # noqa: BLE001
        out = {"fatal": repr(e)}
    print("ZYVEN_DIFF_REPORT=" + json.dumps(out, ensure_ascii=False, default=str))
