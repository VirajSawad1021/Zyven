"""Egress proxy for the sandbox: forwards only to allowlisted hosts. Runs in its own container (standard library only).

The sandboxed program sits on a Docker network with no route out (`--internal`) and gets HTTPS_PROXY / HTTP_PROXY
pointing here. This proxy is the only thing on that network that can also reach the internet, and it forwards only to
hosts on the allowlist:

  * HTTPS: `CONNECT host:443` is tunnelled byte for byte. TLS is never terminated or inspected; the host name in the
    CONNECT line is what is checked.
  * HTTP: absolute-URI requests (`GET http://host/path`) to an allowed host on port 80 are forwarded.

Allowlist (ZYVEN_ALLOW_HOSTS, comma separated): `api.example.com` matches exactly; `*.example.com` matches any subdomain
(not example.com itself). Only ports 443 and 80. IP-address literals are refused (they would bypass name checks).
Every decision is printed as one JSON line, so the run can show what was allowed and refused.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import sys

PORTS = {443, 80}


def allowed(host: str, port: int, rules: list[str]) -> bool:
    host = host.strip().lower().rstrip(".")
    if port not in PORTS or not host:
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return False  # an IP literal skips the name the allowlist is about
    except ValueError:
        pass
    for r in rules:
        r = r.strip().lower().rstrip(".")
        if not r:
            continue
        if r.startswith("*."):
            if host.endswith(r[1:]) and host != r[2:]:
                return True
        elif host == r:
            return True
    return False


def split_hostport(target: str, default: int) -> tuple[str, int]:
    if target.startswith("["):  # [v6]:port
        host, _, rest = target[1:].partition("]")
        return host, int(rest.lstrip(":") or default)
    host, sep, port = target.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return target, default


def log(**kw) -> None:
    print(json.dumps(kw), flush=True)


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:  # noqa: BLE001
            pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, rules: list[str]) -> None:
    try:
        first = (await asyncio.wait_for(reader.readline(), 30)).decode("latin-1").strip()
        headers = []
        while (line := await asyncio.wait_for(reader.readline(), 30)) not in (b"\r\n", b"\n", b""):
            headers.append(line)
        method, target, version = (first.split(" ") + ["", "", ""])[:3]
        if method.upper() == "CONNECT":
            host, port = split_hostport(target, 443)
            path = None
        elif target.lower().startswith("http://"):
            rest = target[7:]
            hostport, _, p = rest.partition("/")
            host, port = split_hostport(hostport, 80)
            path = "/" + p
        else:
            log(allowed=False, host="", reason="not a proxy request", line=first[:80])
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            return
        if not allowed(host, port, rules):
            log(allowed=False, host=host, port=port)
            writer.write(f"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n\r\n"
                         f"zyven egress: {host}:{port} is not on this sandbox's allowlist\n".encode())
            return
        try:
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, port), 20)
        except (OSError, asyncio.TimeoutError) as e:
            log(allowed=True, host=host, port=port, error=type(e).__name__)
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            return
        log(allowed=True, host=host, port=port)
        if path is None:
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            kept = [h for h in headers if not h.lower().startswith((b"proxy-", b"connection:"))]
            up_w.write(f"{method} {path} {version}\r\n".encode() + b"".join(kept) + b"Connection: close\r\n\r\n")
        await writer.drain()
        await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError):
        pass
    finally:
        try:
            await writer.drain()
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def main() -> None:
    rules = [h for h in os.environ.get("ZYVEN_ALLOW_HOSTS", "").split(",") if h.strip()]
    port = int(os.environ.get("ZYVEN_PROXY_PORT", "8080"))
    server = await asyncio.start_server(lambda r, w: handle(r, w, rules), "0.0.0.0", port)
    log(ready=True, port=port, allow=rules)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
