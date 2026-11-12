"""The egress allowlist: the proxy's rules (pure), the report, and (with Docker) the real network behaviour."""

from __future__ import annotations

import json
import os

import pytest

from zyven.mcpverify.checks import run_checks
from zyven.sandbox.egress_proxy import allowed, split_hostport


def test_exact_and_wildcard_hosts():
    rules = ["api.example.com", "*.figma.com"]
    assert allowed("api.example.com", 443, rules) and allowed("API.Example.com.", 443, rules)
    assert not allowed("example.com", 443, rules) and not allowed("evil-api.example.com", 443, rules)
    assert allowed("api.figma.com", 443, rules) and allowed("a.b.figma.com", 80, rules)
    assert not allowed("figma.com", 443, rules)            # the wildcard is for subdomains only
    assert not allowed("notfigma.com", 443, rules)         # a suffix match must be on a dot boundary


def test_only_web_ports_and_no_ip_literals():
    rules = ["api.example.com", "*.example.com"]
    assert not allowed("api.example.com", 22, rules)
    assert not allowed("151.101.0.223", 443, ["151.101.0.223"])  # an IP literal skips the name check
    assert not allowed("[::1]", 443, ["::1"])
    assert not allowed("", 443, rules)


def test_split_hostport():
    assert split_hostport("api.example.com:443", 80) == ("api.example.com", 443)
    assert split_hostport("api.example.com", 80) == ("api.example.com", 80)
    assert split_hostport("[2001:db8::1]:8443", 443) == ("2001:db8::1", 8443)


def _obs(egress):
    tool = {"name": "t", "description": "d", "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"readOnlyHint": True}}
    return {"target": "x", "started": True, "sandboxed": True, "tools": [tool], "tools_again": [tool], "egress": egress}


def test_isolation_reports_the_allowlist_and_refused_hosts():
    ok = run_checks(_obs({"hosts": ["api.example.com"], "decisions": [
        {"allowed": True, "host": "api.example.com", "port": 443}]}))
    iso = next(c for c in ok.checks if c.name == "isolation")
    assert iso.status == "PASS" and "limited to api.example.com" in iso.detail and "reached api.example.com" in iso.detail
    bad = run_checks(_obs({"hosts": ["api.example.com"], "decisions": [
        {"allowed": False, "host": "telemetry.example.net", "port": 443}]}))
    iso = next(c for c in bad.checks if c.name == "isolation")
    assert iso.status == "WARN" and "telemetry.example.net:443" in iso.findings[0]


@pytest.mark.skipif(os.environ.get("ZYVEN_DOCKER_TESTS") != "1", reason="set ZYVEN_DOCKER_TESTS=1 (needs Docker and internet)")
def test_real_allowlist_in_the_sandbox():
    from zyven.sandbox.egress import Egress
    from zyven.sandbox.runner import SandboxPolicy, run
    probe = r'''
import json, socket, urllib.request
out = {}
for name, url in (("allowed", "https://pypi.org/simple/"), ("refused", "https://example.com/")):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            out[name] = r.status
    except Exception as e:
        out[name] = type(e).__name__ + ": " + str(e)[:80]
try:
    socket.create_connection(("151.101.0.223", 443), timeout=8).close()
    out["direct"] = "connected"
except Exception as e:
    out["direct"] = type(e).__name__
print("RESULT=" + json.dumps(out))
'''
    with Egress(["pypi.org"]) as eg:
        res = run(["python", "-c", probe], {}, SandboxPolicy(network_name=eg.network, extra_env=eg.env(), timeout_s=120),
                  workdir="/tmp")
        out = json.loads(next(ln for ln in res.stdout.splitlines() if ln.startswith("RESULT="))[7:])
        decisions = eg.decisions()
    assert out["allowed"] == 200
    assert "403" in out["refused"]
    assert out["direct"] != "connected"
    assert {"allowed": False, "host": "example.com", "port": 443} in decisions


FETCH_SERVER = '''
import urllib.request
from mcp.server.mcpserver import MCPServer
server = MCPServer(name="fetcher")

@server.tool(name="fetch")
def fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return {"status": r.status}
    except Exception as e:
        return {"status": 0, "error": type(e).__name__ + ": " + str(e)[:80]}

if __name__ == "__main__":
    server.run("stdio")
'''


@pytest.mark.skipif(os.environ.get("ZYVEN_DOCKER_TESTS") != "1", reason="set ZYVEN_DOCKER_TESTS=1 (needs Docker and internet)")
def test_a_skill_reaches_only_its_allowlisted_host_at_run_time(tmp_path):
    import asyncio
    import subprocess
    from zyven.agent.mcp_tools import ToolBox
    from zyven.memory.skills import skill_server_spec
    skill = tmp_path / "fetcher"
    skill.mkdir()
    (skill / "server.py").write_text(FETCH_SERVER, encoding="utf-8")
    (skill / "provenance.json").write_text(json.dumps({"network_hosts": ["pypi.org"]}), encoding="utf-8")
    spec = skill_server_spec("fetcher", skill, None)
    assert spec.egress_hosts == ["pypi.org"]

    async def go():
        async with ToolBox() as tb:
            await tb.add_server(spec)
            ok = await tb.call("fetch", {"url": "https://pypi.org/simple/"})
            no = await tb.call("fetch", {"url": "https://example.com/"})
            return ok, no

    (ok_flag, ok_text), (no_flag, no_text) = asyncio.run(go())
    assert '"status": 200' in ok_text.replace("'", '"') or '"status":200' in ok_text.replace(" ", "")
    assert "403" in no_text
    left = subprocess.run(["docker", "ps", "-a", "--filter", "name=zyven-proxy", "--format", "{{.Names}}"],
                          capture_output=True, text=True).stdout.strip()
    nets = subprocess.run(["docker", "network", "ls", "--filter", "name=zyven-egress", "--format", "{{.Name}}"],
                          capture_output=True, text=True).stdout.strip()
    assert left == "" and nets == ""  # the proxy and its network are gone with the toolbox


def test_gates_run_on_the_egress_network_when_a_skill_has_an_allowlist(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import zyven.compiler.verify as v
    from zyven.ai.schemas import CapabilitySpec
    seen = []
    monkeypatch.setattr(v, "run", lambda cmd, mounts, policy, **k: seen.append(policy)
                        or SimpleNamespace(ok=False, stdout="", stderr="stop here"))
    (tmp_path / "server.py").write_text("x = 1\n", encoding="utf-8")
    spec = CapabilitySpec(name="s", title="s", summary="", tools=[], included_symbols=[], relevant_tests=[])
    eg = SimpleNamespace(network="zyven-egress-test", env=lambda: {"HTTPS_PROXY": "http://zyven-proxy-test:8080"})
    v.verify(tmp_path, spec, tmp_path, set(), run_upstream=False, egress=eg)
    assert seen and seen[0].network_name == "zyven-egress-test"
    assert seen[0].extra_env["HTTPS_PROXY"] == "http://zyven-proxy-test:8080" and "PYTHONPATH" in seen[0].extra_env
    seen.clear()
    v.verify(tmp_path, spec, tmp_path, set(), run_upstream=False)
    assert seen[0].network_name == "" and "HTTPS_PROXY" not in seen[0].extra_env  # no allowlist: --network none
