"""Does `zyven board` start and answer on this operating system? CI runs it on Linux, macOS and Windows.

Starts the board on a free port with an empty board folder and no model key, waits for it, then checks:

    the landing page loads           the single-file page loads     read-only APIs answer with JSON
    a request with a foreign Host is refused (the local-only guard)

    uv run python scripts/smoke_board.py
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

APIS = ["/api/cards", "/api/skills", "/api/catalog", "/api/stats", "/api/runtimes", "/api/runs", "/api/connections"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, host: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    board = tempfile.mkdtemp(prefix="zyven-board-")
    env = {**os.environ, "ZYVEN_HOME": board, "MODEL_API_KEY": ""}
    proc = subprocess.Popen([sys.executable, "-m", "zyven.cli", "board", "--port", str(port), "--board-dir", board],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(120):  # up to 60 s to start
            if proc.poll() is not None:
                print(proc.stdout.read() if proc.stdout else "")
                print(f"FAIL  the board exited with code {proc.returncode} before answering")
                return 1
            try:
                if get(base + "/")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            print("FAIL  the board did not answer within 60 s")
            return 1
        results: dict[str, bool] = {}
        for path in ["/", "/legacy"]:  # /legacy is the single-file page, served with or without the built site
            status, body = get(base + path)
            results[f"GET {path} -> 200 with a page"] = status == 200 and b"<" in body[:2000]
        for path in APIS:
            status, body = get(base + path)
            try:
                json.loads(body or b"null")
                ok = status == 200
            except ValueError:
                ok = False
            results[f"GET {path} -> 200 JSON"] = ok
            if not ok:
                print(f"  {path}: {status} {body[:200]!r}")
        status, _ = get(base + "/api/stats", host="evil.example")
        results["a foreign Host header is refused"] = status in (400, 403, 421)
        for what, ok in results.items():
            print(f"{'PASS' if ok else 'FAIL'}  {what}")
        return 0 if all(results.values()) else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
