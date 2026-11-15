"""`zyven verify` results as SARIF 2.1.0, the format GitHub code scanning (and most security dashboards) read.

Every finding gets a stable rule ID such as `descriptions/hide-from-user`. The IDs are also what a precision study
counts by: label each finding, then group by rule to see which ones are worth their noise.

The isolation check is left out. It says where the check ran, not something about the server.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from zyven.mcpverify.checks import FAIL, INSTRUCTION_PATTERNS, WARN, Report

INFO_URI = "https://github.com/VirajSawad1021/Zyven"
HELP_URI = INFO_URI + "#verify-any-mcp-server"

_INSTRUCTION_IDS = ["ignore-instructions", "hide-from-user", "instruction-block", "system-prompt",
                    "do-something-first", "credential-file", "secret-forwarding", "send-to-url", "redirect-tool"]
assert len(_INSTRUCTION_IDS) == len(INSTRUCTION_PATTERNS), "name every instruction pattern's rule"

# (rule ID, text that identifies the finding, what the rule means). The part before "/" is the check; within a check
# the first match wins, so the hidden-text rules come before the instruction patterns they can contain.
RULES: list[tuple[str, str, str]] = [
    ("handshake/failed", "", "The server did not start, or did not complete the MCP handshake in time."),
    ("handshake/no-tools", "", "The server started but offers no tools."),
    ("schemas/duplicate-name", "duplicate tool names", "Two tools have the same name."),
    ("schemas/invalid-name", "name is not 1-128", "A tool name uses characters or a length MCP does not allow."),
    ("schemas/invalid-schema", "is not valid JSON Schema", "An input or output schema is not valid JSON Schema."),
    ("schemas/invalid-schema", "is not an object", "An input or output schema is not valid JSON Schema."),
    ("schemas/input-not-object", "inputSchema type is not 'object'", "A tool's inputSchema is not of type object."),
    ("schemas/undefined-required", "required parameters not defined",
     "A parameter is marked required but has no definition."),
    ("schemas/undocumented-parameter", "parameters without a description",
     "Parameters have no description, so the model has to guess what to pass."),
    ("descriptions/hidden-unicode-tags", "invisible Unicode tag characters",
     "Invisible Unicode tag characters carry text a person cannot see but the model reads."),
    ("descriptions/bidi-override", "bidirectional override",
     "Bidirectional override characters make text display differently from what it says."),
    ("descriptions/invisible-characters", "invisible format characters", "Invisible format characters in the text."),
    ("descriptions/terminal-escapes", "terminal escape sequences",
     "Terminal escape sequences can hide text, move the cursor, plant links or write the clipboard in a CLI client."),
    ("descriptions/control-characters", "control characters",
     "Control characters such as backspace can rewrite what is displayed."),
    *[(f"descriptions/{rid}", why, f"Text aimed at the model: {why}.")
      for rid, (_, why) in zip(_INSTRUCTION_IDS, INSTRUCTION_PATTERNS)],
    ("descriptions/base64-blob", "long base64-like blob", "A long encoded blob in text the model reads."),
    ("descriptions/missing-description", "no description", "A tool has no description."),
    ("descriptions/long-description", "unusually long", "A description is unusually long; read it."),
    ("annotations/contradictory", "both read-only and destructive", "A tool is marked both read-only and destructive."),
    ("annotations/missing-read-only-hint", "no readOnlyHint",
     "A tool does not say whether it is read-only, so clients must assume it changes things."),
    ("stability/changed-between-connections", "changed between two connections",
     "The tool definitions differed between two connections a few seconds apart."),
    ("stability/lock-mismatch", "differ from the lock file", "Tool definitions differ from the committed lock file."),
    ("stability/tool-removed", "no longer offered", "A tool in the lock file is no longer offered."),
    ("stability/tool-added", "new tools since the lock file", "The server offers tools the lock file does not list."),
    ("stability/server-renamed", "server name changed", "The server reports a different name than when locked."),
    ("stability/server-version-changed", "server version changed",
     "A new server version: its code can change while every tool definition stays the same."),
    ("stability/launch-changed", "launch command changed", "The launch command differs from the lock file."),
    ("stability/url-changed", "server URL changed", "The server URL differs from the lock file."),
    ("stability/image-changed", "different build", "The container image now resolves to a different build."),
    ("stability/new-hosts", "now contacts hosts", "The server contacts hosts it did not when locked."),
    ("stability/second-connection-failed", "second connection failed",
     "A second connection failed, so stability could not be checked."),
    ("robustness/server-died", "stopped answering", "The server stopped answering after invalid input."),
    ("robustness/invalid-input-accepted", "", "A tool accepted input its own schema forbids."),
    ("pinning/unpinned-launch", "", "The launch command can run a different release next time."),
]

# Rules that are about security rather than correctness; GitHub uses security-severity to rank them.
_SEVERITY = {"descriptions": "8.0", "stability": "7.0", "pinning": "5.0", "robustness": "5.0"}
_SECURITY_CORRECTNESS = {"schemas/", "handshake/", "descriptions/missing", "descriptions/long",
                         "stability/second-connection", "annotations/missing"}


def rule_of(check: str, finding: str) -> str:
    """The stable rule ID for one finding of one check."""
    for rid, needle, _ in RULES:
        if rid.split("/")[0] == check and needle and needle in finding:
            return rid
    fallback = {"robustness": "robustness/invalid-input-accepted", "pinning": "pinning/unpinned-launch"}
    return fallback.get(check, f"{check}/other")


def _rule_entries(used: set[str]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for rid, _, text in RULES + [(u, "", "Other finding of this check.") for u in sorted(used)]:
        if rid in seen or rid not in used:
            continue
        check = rid.split("/")[0]
        security = not any(rid.startswith(p) for p in _SECURITY_CORRECTNESS)
        props: dict[str, Any] = {"tags": ["security" if security else "correctness", "mcp"]}
        if security and check in _SEVERITY:
            props["security-severity"] = _SEVERITY[check]
        seen[rid] = {"id": rid, "name": rid.replace("/", "_").replace("-", "_"),
                     "shortDescription": {"text": text}, "helpUri": HELP_URI, "properties": props}
    return list(seen.values())


def _uri(path: str) -> str:
    p = Path(path)
    try:
        p = p.resolve().relative_to(Path.cwd().resolve())
    except (OSError, ValueError):
        pass
    return p.as_posix()


def artifact_for(lock: str | None, command: list[str] | None) -> str:
    """Which file the results are attached to: the lock file if there is one, else a file named in the command
    (`node dist/index.js`, `python server.py`), else a placeholder."""
    if lock:
        return lock
    for a in (command or [])[1:]:  # the first word is the program (node, python), not the server's file
        if not a.startswith("-") and Path(a).is_file():
            return a
    return "mcp-server"


def to_sarif(reports: list[tuple[Report, str]]) -> dict[str, Any]:
    """One SARIF run for one or more servers; each report comes with the file its results are attached to."""
    try:
        from importlib.metadata import version
        tool_version = version("zyven")
    except Exception:  # running from a checkout without an installed distribution
        from zyven import __version__ as tool_version
    results: list[dict[str, Any]] = []
    used: set[str] = set()
    for r, artifact in reports:
        label = " ".join(x for x in (r.server.get("name"), r.server.get("version")) if x) or r.target
        location = [{"physicalLocation": {"artifactLocation": {"uri": _uri(artifact)},
                                          "region": {"startLine": 1}}}]
        for c in r.checks:
            if c.name == "isolation" or c.status not in (FAIL, WARN):
                continue
            items = [(f, i < c.failing) for i, f in enumerate(c.findings)]
            if not items:  # a failed or warned check with nothing itemised, e.g. the handshake
                rid = ({FAIL: "handshake/failed", WARN: "handshake/no-tools"}[c.status] if c.name == "handshake"
                       else f"{c.name}/other")
                items = [(c.detail, c.status == FAIL)]
            else:
                rid = None
            for text, failing in items:
                rule = rid or rule_of(c.name, text)
                used.add(rule)
                fp = hashlib.sha256(f"{r.target}|{rule}|{text}".encode("utf-8")).hexdigest()[:32]
                results.append({"ruleId": rule, "level": "error" if failing else "warning",
                                "message": {"text": f"{label}: {text}"}, "locations": location,
                                "partialFingerprints": {"zyvenFinding/v1": fp}})
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "zyven verify", "informationUri": INFO_URI, "version": str(tool_version),
                                "rules": _rule_entries(used)}},
            "results": results,
        }],
    }
