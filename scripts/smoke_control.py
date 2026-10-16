"""Smoke test for the Control Center API against a running board (default http://127.0.0.1:8765).

Checks: a Docker run streams output and reports file changes, the network is off by default, bad input is
rejected, and a scheduled run waits for its start time.  Run: python scripts/smoke_control.py
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def wait(run_id, done=("COMPLETED", "FAILED", "CANCELLED"), timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        _, d = call("GET", f"/api/runs/{run_id}")
        if d["status"] in done:
            return d
        time.sleep(1)
    raise SystemExit(f"timeout waiting for {run_id}: {d['status']}")


fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(name)


cmd = ('echo hello; python -c "print(6*7)"; echo result > out.txt; '
       '(python -c "import urllib.request;urllib.request.urlopen(\'http://example.com\',timeout=3)" 2>/dev/null '
       '&& echo NET_ON) || echo NET_OFF')
code, run = call("POST", "/api/runs", {"runtime": "docker", "title": "smoke", "prompt": cmd})
check("create docker run", code == 200 and run.get("id"), str(code))
d = wait(run["id"])
out = [l["text"] for l in d["log"] if l["kind"] == "out"]
check("run completed", d["status"] == "COMPLETED", d["status"])
check("live output captured", "hello" in out and "42" in out, str(out))
check("network is off by default", "NET_OFF" in out and "NET_ON" not in out)
check("file change reported", d["files"] and "out.txt" in d["files"]["added"], str(d["files"]))

check("bad image rejected", call("POST", "/api/runs", {"runtime": "docker", "prompt": "x", "image": "a b; rm"})[0] == 400)
check("non-https repo rejected", call("POST", "/api/runs", {"runtime": "docker", "prompt": "x", "repo_url": "file:///etc"})[0] == 400)
check("unknown runtime rejected", call("POST", "/api/runs", {"runtime": "nope", "prompt": "x"})[0] == 400)

start = time.time() + 8
_, sched = call("POST", "/api/runs", {"runtime": "docker", "prompt": "echo scheduled-ok", "run_at": start})
check("scheduled run waits", sched["status"] == "SCHEDULED", sched["status"])
d2 = wait(sched["id"])
check("scheduled run ran after its start time", d2["status"] == "COMPLETED" and d2["updated"] >= start, d2["status"])

_, slow = call("POST", "/api/runs", {"runtime": "docker", "prompt": "sleep 60"})
time.sleep(4)
call("POST", f"/api/runs/{slow['id']}/cancel")
d3 = wait(slow["id"], timeout=30)
check("cancel stops a running container", d3["status"] == "CANCELLED", d3["status"])

print("\nall passed" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
