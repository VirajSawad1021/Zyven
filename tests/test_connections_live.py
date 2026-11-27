"""Live checks of the Gmail, Slack and GitHub connections against real test accounts. Skipped unless asked for.

Each service has its own switch, because each needs its own throwaway account:

    ZYVEN_GMAIL_LIVE=1    a test Google account, connected on the board as "Gmail (Google hosted)" and signed in
    ZYVEN_SLACK_LIVE=1    a Slack app in a test workspace, connected as "Slack (bot token, community server)" or
                          "Slack (hosted by Slack)"
    ZYVEN_GITHUB_LIVE=1   a token for a throwaway GitHub account or repository, connected as "GitHub (all repository tools)"

Set the connection up once on the board's Connections page, which does the OAuth sign-in or stores the pasted token.
The tests then use that connection the way `zyven verify --connection` does: through the board's own store, so tokens
are refreshed there and never copied (a copied refresh token can sign the board out). They do not change the board:
they never record tools or pins, and never switch a connection on or off.

    ZYVEN_HOME=<board folder>              which board (default: workspace/ in a checkout, else ~/.zyven)
    ZYVEN_<SERVICE>_CONNECTION=<name>      the connection's name, if it is not the template's

What is checked for each:
  * it connects and lists tools, and `zyven verify` passes: handshake, schemas, descriptions, annotations, and
    whatever the tools marked read-only return when called with valid input (read-only tools only: this is a real
    account);
  * a tool that is not marked read-only asks the approval gate first, and a "no" means it is never sent to the service;
  * the claim on the template is true (Gmail can draft but not send; posting to Slack, when the server offers it,
    needs approval; GitHub has write tools that need approval).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from zyven import paths

SERVICES = {
    # service: (switch, connection names to try, in order)
    "gmail": ("ZYVEN_GMAIL_LIVE", ["Gmail (Google hosted)", "Gmail"]),
    "slack": ("ZYVEN_SLACK_LIVE", ["Slack (bot token, community server)", "Slack (hosted by Slack)", "Slack"]),
    "github": ("ZYVEN_GITHUB_LIVE", ["GitHub (all repository tools)", "GitHub"]),
}


def _live(service: str) -> Any:
    flag = SERVICES[service][0]
    return pytest.mark.skipif(os.environ.get(flag) != "1",
                              reason=f"set {flag}=1 (needs a {service} test account connected on the board)")


@pytest.fixture(autouse=True)
def _board_keychain(monkeypatch):
    """conftest.py keeps every other test away from the real keychain (ZYVEN_SECRETS=file), but the board's
    connection secrets are encrypted with a key kept there. ZYVEN_LIVE_SECRETS=file is for a board that has no key
    (a keychain-less machine)."""
    monkeypatch.setenv("ZYVEN_SECRETS", os.environ.get("ZYVEN_LIVE_SECRETS", "keychain"))


def _board() -> Path:
    return paths.home()


def _connection(service: str) -> dict[str, Any]:
    """The board's connection for this service, signed in. Fails (not skips) with what to do: the switch was set."""
    from zyven.connections.store import ConnectionStore

    store = ConnectionStore(_board())
    conns = store.list()
    wanted = os.environ.get(f"ZYVEN_{service.upper()}_CONNECTION")
    names = [wanted] if wanted else SERVICES[service][1]
    conn = next((c for n in names for c in conns if c.get("name", "").lower() == n.lower()), None)
    if conn is None:
        known = ", ".join(sorted(c.get("name", c["id"]) for c in conns)) or "none"
        pytest.fail(f"no {service} connection on the board in {_board()} (looked for {names}; connected: {known}). "
                    f"Add it on the board's Connections page, or set ZYVEN_{service.upper()}_CONNECTION.")
    if conn.get("oauth") and not conn.get("signed_in"):
        pytest.fail(f"{conn['name']} is not signed in: sign in on the board's Connections page first")
    return conn


def _verify(conn: dict[str, Any]) -> Any:
    from zyven.mcpverify import format_report, verify_connection

    report = verify_connection(_board(), conn["id"], call="read-only", timeout=90)
    print(format_report(report, verbose=True))  # shown with -s: the record for LIMITATIONS.md
    return report


def _gate_check(conn: dict[str, Any]) -> tuple[list[str], list[str], list[tuple[str, dict[str, Any]]],
                                                tuple[bool, str] | None]:
    """Connect through the agent's toolbox with a gate that always says no, and try one tool that is not read-only.
    Returns (read-only tools, tools needing approval, what the gate was asked, the call's result)."""
    from zyven.agent.mcp_tools import ToolBox
    from zyven.connections.probe import needs_approval, server_for
    from zyven.connections.store import ConnectionStore
    from zyven.mcpverify.probe import valid_input

    store = ConnectionStore(_board())
    asked: list[tuple[str, dict[str, Any]]] = []

    async def deny(tool: str, arguments: dict[str, Any]) -> bool:
        asked.append((tool, arguments))
        return False

    async def go() -> tuple[list[str], list[str], tuple[bool, str] | None]:
        from mcp import Client

        async with Client(server_for(store, conn["id"], conn), read_timeout_seconds=60) as client:
            tools = (await client.list_tools()).tools  # with annotations, which the toolbox does not keep
        readers = [t.name for t in tools if not needs_approval(t)]
        writers = [t for t in tools if needs_approval(t)]
        if not writers:
            return readers, [], None
        async with ToolBox() as tb:
            await tb.add_transport("live", server_for(store, conn["id"], conn), gate=deny)
            t = writers[0]
            schema = t.model_dump(by_alias=True, exclude_none=True, mode="json")
            return readers, [w.name for w in writers], await tb.call(t.name, valid_input(schema))

    readers, writers, result = asyncio.run(asyncio.wait_for(go(), 120))
    return readers, writers, asked, result


def _check(service: str) -> tuple[Any, list[str]]:
    from zyven.mcpverify.checks import FAIL, SKIP

    conn = _connection(service)
    report = _verify(conn)
    by_name = {c.name: c for c in report.checks}
    assert by_name["handshake"].status != FAIL and report.tools, f"{conn['name']} listed no tools"
    # These say the connection itself is broken or unsafe to use. The rest judge how the third-party server describes
    # itself (slack-mcp-server 1.3.0 marks six read tools both read-only and destructive): a finding about that
    # server, printed for the record, not a failure of Zyven's connection.
    must_pass = ("handshake", "schemas", "descriptions", "results")
    failed = [f"{c.name}: {c.detail}" for c in report.checks if c.status == FAIL and c.name in must_pass]
    assert not failed, f"zyven verify failed on {conn['name']}: {failed}"
    findings = [f"{c.name}: {c.detail}" for c in report.checks if c.status == FAIL and c.name not in must_pass]
    print(f"server findings (not failures of the connection): {findings or 'none'}")

    readers, writers, asked, result = _gate_check(conn)
    print(f"read-only (run freely): {readers}\nneed approval: {writers}")
    if readers:
        assert by_name["results"].status != SKIP, f"read-only tools {readers} were listed but none was called"
    if writers:
        assert asked and asked[0][0] == writers[0], "a tool that is not read-only ran without asking the gate"
        assert result is not None and result[0] is False and result[1].startswith("Denied"), result
    return report, writers


@_live("gmail")
def test_live_gmail_connects_verifies_and_cannot_send():
    report, _ = _check("gmail")
    names = [t.lower() for t in report.tools]
    assert any("draft" in n for n in names), f"no draft tool: {report.tools}"
    assert not any("send" in n for n in names), f"the template says Gmail cannot send, but it lists {report.tools}"


@_live("slack")
def test_live_slack_connects_verifies_and_gates_posting():
    report, writers = _check("slack")
    # slack-mcp-server lists its posting tool (conversations_add_message) only with SLACK_MCP_ADD_MESSAGE_TOOL set;
    # Slack's hosted server always has one. Either way, posting must never run without approval.
    posts = [t for t in report.tools if any(w in t.lower() for w in ("post", "send", "add_message"))]
    print(f"posting tools: {posts or 'none listed'}")
    assert set(posts) <= set(writers), f"posting without approval: {sorted(set(posts) - set(writers))}"


@_live("github")
def test_live_github_connects_verifies_and_gates_writes():
    report, writers = _check("github")
    writes = [t for t in report.tools if t.lower().startswith(("create", "update", "push", "merge", "delete"))]
    assert writes, f"no write tool listed: {report.tools}"
    assert set(writes) <= set(writers), f"write tools that would run without approval: {sorted(set(writes) - set(writers))}"
