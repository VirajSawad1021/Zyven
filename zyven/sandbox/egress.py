"""Network for a sandbox, limited to named hosts (an allowlist), through an egress proxy.

    with Egress(["api.example.com"]) as eg:
        policy = SandboxPolicy(network_name=eg.network, extra_env=eg.env())
        ... run the sandboxed program ...
        eg.decisions()   # every connection the proxy allowed or refused

The sandboxed container joins a Docker network created with --internal: it has no route out. The proxy container
(egress_proxy.py, same image, read-only, no capabilities, non-root) is on that network and on the default one, and
forwards only to allowlisted hosts. A program that ignores HTTPS_PROXY and connects directly has nowhere to go.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path

PROXY_PORT = 8080
SCRIPT = Path(__file__).with_name("egress_proxy.py")


def _docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


class EgressError(RuntimeError):
    pass


class Egress:
    def __init__(self, hosts: list[str], image: str | None = None) -> None:
        from zyven.sandbox.runner import DEFAULT_IMAGE, _docker_path
        self.hosts = [h.strip() for h in hosts if h.strip()]
        if not self.hosts:
            raise ValueError("an egress allowlist needs at least one host")
        self.image = image or DEFAULT_IMAGE
        tag = uuid.uuid4().hex[:10]
        self.network = f"zyven-egress-{tag}"
        self.proxy = f"zyven-proxy-{tag}"
        self._script = _docker_path(SCRIPT)

    @property
    def url(self) -> str:
        return f"http://{self.proxy}:{PROXY_PORT}"

    def env(self) -> dict[str, str]:
        u = self.url
        return {"HTTPS_PROXY": u, "HTTP_PROXY": u, "https_proxy": u, "http_proxy": u, "NO_PROXY": "", "no_proxy": ""}

    def __enter__(self) -> "Egress":
        r = _docker("network", "create", "--internal", self.network)
        if r.returncode != 0:
            raise EgressError(f"could not create the sandbox network: {r.stderr.strip()[:200]}")
        r = _docker("run", "-d", "--rm", "--name", self.proxy, "--hostname", "zyven-egress",
                    "--user", "1000:1000", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                    "--memory", "128m", "--cpus", "0.5", "--pids-limit", "64",
                    "-e", f"ZYVEN_ALLOW_HOSTS={','.join(self.hosts)}", "-e", f"ZYVEN_PROXY_PORT={PROXY_PORT}",
                    "-v", f"{self._script}:/opt/zyven/egress_proxy.py:ro",
                    self.image, "python", "/opt/zyven/egress_proxy.py")
        if r.returncode != 0:
            self._teardown()
            raise EgressError(f"could not start the egress proxy: {r.stderr.strip()[:200]}")
        r = _docker("network", "connect", self.network, self.proxy)
        if r.returncode != 0:
            self._teardown()
            raise EgressError(f"could not attach the egress proxy: {r.stderr.strip()[:200]}")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any(d.get("ready") for d in self._lines()):
                return self
            time.sleep(0.3)
        self._teardown()
        raise EgressError("the egress proxy did not start")

    def _lines(self) -> list[dict]:
        r = _docker("logs", self.proxy, timeout=20)
        out = []
        for ln in (r.stdout or "").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def decisions(self) -> list[dict]:
        """Every connection the proxy decided on: {"allowed": bool, "host": ..., "port": ...}."""
        return [d for d in self._lines() if "allowed" in d]

    def _teardown(self) -> None:
        _docker("rm", "-f", self.proxy, timeout=30)
        _docker("network", "rm", self.network, timeout=30)

    def __exit__(self, *exc) -> None:
        self.final = self.decisions() if self._exists() else []
        self._teardown()

    def _exists(self) -> bool:
        return _docker("inspect", self.proxy, timeout=15).returncode == 0
