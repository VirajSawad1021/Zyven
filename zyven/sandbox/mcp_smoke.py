"""MCP protocol smoke test, executed INSIDE the sandbox container.

Usage: python /opt/zyven/mcp_smoke.py /skill/server.py /skill/smoke.json
smoke.json: {"tools": {"<name>": {"args": {...}, "returns": ["field", ...], "required": ["param", ...]}}}
Prints one JSON report to stdout.
"""

import asyncio
import json
import os
import runpy
import sys
import traceback


def _ws(v):
    """Compare results ignoring whitespace inside strings (tools may echo the caller's spelling back)."""
    if isinstance(v, str):
        return "".join(v.split())
    if isinstance(v, dict):
        return {k: _ws(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ws(x) for x in v]
    return v


def _direct_traceback(server_path: str, tool: str, args: dict) -> str:
    """Call the tool function directly (same sandbox) to capture the real exception for the repair role."""
    try:
        ns = runpy.run_path(server_path, run_name="zyven_direct")
        ns[tool](**args)
        return "direct call succeeded (failure is in MCP result handling or return shape)"
    except Exception:  # noqa: BLE001
        return "".join(traceback.format_exc().splitlines(keepends=True)[-8:])

from mcp import Client
from mcp.client.stdio import StdioServerParameters


def _payload(result):
    if result.structured_content is not None:
        data = result.structured_content
        # Servers may wrap a dict return as {"result": {...}}.
        if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], dict):
            data = data["result"]
        return data
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return text


async def main(server_path: str, plan_path: str) -> dict:
    plan = json.load(open(plan_path, encoding="utf-8"))
    report = {"server_started": False, "listed_tools": [], "missing_tools": [], "calls": [], "invalid_calls": []}
    params = StdioServerParameters(command=sys.executable, args=[server_path], env={"PYTHONPATH": os.environ.get("PYTHONPATH", "/src")})
    async with Client(params, read_timeout_seconds=30) as client:
        report["server_started"] = True
        listing = await client.list_tools()
        names = [t.name for t in listing.tools]
        report["listed_tools"] = names
        report["missing_tools"] = [t for t in plan["tools"] if t not in names]
        for name, case in plan["tools"].items():
            if name not in names:
                continue
            entry = {"tool": name, "args": case["args"], "ok": False}
            try:
                res = await client.call_tool(name, case["args"])
                data = _payload(res)
                entry["is_error"] = bool(res.is_error)
                entry["output"] = data if isinstance(data, (dict, list, str, int, float, bool)) else str(data)
                missing = [f for f in case["returns"] if not (isinstance(data, dict) and f in data)]
                entry["missing_fields"] = missing
                entry["ok"] = not res.is_error and not missing
                if res.is_error:
                    entry["traceback"] = _direct_traceback(server_path, name, case["args"])
            except Exception as e:  # noqa: BLE001
                entry["exception"] = repr(e)
                entry["traceback"] = _direct_traceback(server_path, name, case["args"])
            report["calls"].append(entry)
            # Robustness: equivalent spellings of the input must give the same result.
            if entry["ok"]:
                for variant in case.get("variants", []):
                    probe = {"tool": name, "args": variant, "ok": False}
                    try:
                        vres = await client.call_tool(name, variant)
                        vdata = _payload(vres)
                        probe["ok"] = not vres.is_error and _ws(vdata) == _ws(entry["output"])
                        probe["output"] = vdata if isinstance(vdata, (dict, list, str, int, float, bool)) else str(vdata)
                        if vres.is_error:
                            probe["traceback"] = _direct_traceback(server_path, name, variant)
                    except Exception as e:  # noqa: BLE001
                        probe["exception"] = repr(e)
                    report.setdefault("robustness", []).append(probe)
            # Invalid call: omit required params. Must produce a tool error, not crash the server.
            if case.get("required"):
                bad = {"ok": False, "tool": name}
                try:
                    res = await client.call_tool(name, {})
                    bad["ok"] = bool(res.is_error)
                    bad["detail"] = "rejected cleanly" if res.is_error else "accepted invalid input"
                except Exception as e:  # noqa: BLE001
                    bad["detail"] = f"exception: {e!r}"
                report["invalid_calls"].append(bad)
        report["still_alive_after_calls"] = bool(await client.list_tools())
    return report


if __name__ == "__main__":
    try:
        out = asyncio.run(main(sys.argv[1], sys.argv[2]))
    except Exception as e:  # noqa: BLE001
        out = {"server_started": False, "fatal": repr(e)}
    print("ZYVEN_SMOKE_REPORT=" + json.dumps(out, ensure_ascii=False, default=str))
