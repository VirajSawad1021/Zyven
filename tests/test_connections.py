"""Connections: secret handling, safety gates, and a real probe of a local MCP server (no network, no models)."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.connections.probe import needs_approval, probe  # noqa: E402
from zyven.connections.store import ConnectionError_, ConnectionStore  # noqa: E402

SERVER = textwrap.dedent('''
    import os
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer("demo")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def lookup(q: str) -> str:
        """Look something up."""
        return "found " + q

    @server.tool()
    def send_message(text: str) -> str:
        """Send a message."""
        return "sent"

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def whoami() -> str:
        """Report the token the server was started with."""
        return os.environ.get("DEMO_TOKEN", "")

    if __name__ == "__main__":
        server.run("stdio")
''')


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOW_STDIO_CONNECTORS", "1")
    return ConnectionStore(tmp_path)


def test_secret_values_are_never_returned_or_listed(store, tmp_path):
    c = store.add(name="Hosted", kind="http", url="https://mcp.example.com/mcp", secrets={"Authorization": "Bearer sk-live-123"})
    assert c["secret_names"] == ["Authorization"] and "sk-live-123" not in json.dumps(store.list())
    assert "sk-live-123" not in (tmp_path / "connections" / "connections.json").read_text(encoding="utf-8")
    assert store.secrets_for(c["id"]) == {"Authorization": "Bearer sk-live-123"}
    store.remove(c["id"])
    assert store.list() == [] and store.secrets_for(c["id"]) == {}


@pytest.mark.parametrize("url", ["http://evil.example.com/mcp", "ftp://x/y", "https://", "javascript:alert(1)", "https://a b"])
def test_only_https_or_localhost_urls_are_accepted(store, url):
    with pytest.raises(ConnectionError_, match="URL"):
        store.add(name="x", kind="http", url=url)


def test_http_localhost_is_allowed_for_development(store):
    assert store.add(name="Local", kind="http", url="http://localhost:8000/mcp")["kind"] == "http"


def test_local_command_connectors_are_refused_unless_explicitly_allowed(tmp_path, monkeypatch):
    monkeypatch.delenv("ZYVEN_ALLOW_STDIO_CONNECTORS", raising=False)
    with pytest.raises(ConnectionError_, match="ZYVEN_ALLOW_STDIO_CONNECTORS=1"):
        ConnectionStore(tmp_path).add(name="x", kind="stdio", command="npx", args=["-y", "thing"])


def test_a_connection_cannot_be_enabled_before_it_is_tested(store):
    c = store.add(name="Hosted", kind="http", url="https://mcp.example.com/mcp")
    with pytest.raises(ConnectionError_, match="test the connection"):
        store.set_enabled(c["id"], True)


def test_probe_lists_tools_and_flags_everything_not_read_only(store, tmp_path):
    script = tmp_path / "demo_server.py"
    script.write_text(SERVER, encoding="utf-8")
    c = store.add(name="Demo", kind="stdio", command=sys.executable, args=[str(script)], secrets={"DEMO_TOKEN": "tok-secret-9"})
    done = asyncio.run(probe(store, c["id"]))
    assert done["error"] is None, done["error"]
    tools = {t["name"]: t for t in done["tools"]}
    assert set(tools) == {"lookup", "send_message", "whoami"}
    assert tools["lookup"]["needs_approval"] is False and tools["send_message"]["needs_approval"] is True
    assert store.set_enabled(c["id"], True)["enabled"] is True


def test_a_failing_connection_records_the_error_without_leaking_the_secret(store):
    c = store.add(name="Broken", kind="stdio", command=sys.executable,
                  args=["-c", "import sys; print('boom tok-secret-9', file=sys.stderr); sys.exit(3)"],
                  secrets={"DEMO_TOKEN": "tok-secret-9"})
    done = asyncio.run(probe(store, c["id"]))
    assert done["tools"] is None and done["enabled"] is False and done["error"]
    assert "tok-secret-9" not in done["error"]


def test_unknown_annotations_mean_ask_first():
    class T:  # a server that sets no hints
        annotations = None
    assert needs_approval(T()) is True


def test_templates_are_well_formed_and_oauth_ones_are_marked_unavailable():
    from zyven.connections.templates import TEMPLATES

    ids = [t["id"] for t in TEMPLATES]
    assert len(ids) == len(set(ids)) and {"notion", "slack", "gmail", "github"} <= set(ids)
    for t in TEMPLATES:
        assert t["kind"] in ("http", "stdio") and t["hint"]
        if t["kind"] == "http":
            assert t["url"] == "" or t["url"].startswith("https://")
        if t.get("oauth"):
            assert t["secrets"] == []  # nothing to paste: they need a sign-in flow we do not have
        else:
            assert t["secrets"] or t["id"] in ("filesystem", "custom-stdio")
