"""Keep other websites from driving the local board.

The board has no login: it is meant for the machine it runs on. But a web page in the user's browser can still send
requests to http://127.0.0.1:<port>, and the board can now run programs, edit files and use connected accounts. Two
cheap checks close the usual routes:

  * the Host header must name this machine (this stops DNS rebinding, where an attacker's domain is pointed at
    127.0.0.1 so its page may read the answers);
  * a request that changes anything must not come from another origin (this stops a page from submitting a
    form or fetch() to the board).

To serve the board on another address on purpose, list the host names in ZYVEN_ALLOWED_HOSTS (comma separated).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

LOCAL = {"127.0.0.1", "localhost", "::1", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in os.environ.get("ZYVEN_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return LOCAL | extra


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8765
        return host.split("]")[0] + "]"
    return host.split(":")[0]


def check(method: str, host_header: str, origin: str | None, allowed: set[str]) -> str | None:
    """None when the request may go ahead, otherwise the reason it is refused."""
    if _host_name(host_header) not in allowed:
        return f"unexpected Host {host_header!r}; the board answers only on this machine"
    if method.upper() not in SAFE_METHODS and origin and origin != "null":
        if (urlparse(origin).hostname or "").lower() not in {h.strip("[]") for h in allowed} | allowed:
            return f"requests that change anything must come from the board itself, not from {origin!r}"
    if method.upper() not in SAFE_METHODS and origin == "null":
        return "requests that change anything must come from the board itself, not from a sandboxed page"
    return None


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def local_only(request: Request, call_next):
        why = check(request.method, request.headers.get("host", ""), request.headers.get("origin"), allowed_hosts())
        if why:
            return JSONResponse({"detail": why}, status_code=403)
        return await call_next(request)
