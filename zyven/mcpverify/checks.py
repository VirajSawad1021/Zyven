"""Checks for any MCP server, built by Zyven or not.

Zyven's six compile gates need the library and a spec. A third-party server has neither, so `zyven verify` checks
what can be checked from the outside, from what the server itself says and does:

  handshake    it starts, completes the MCP handshake and lists its tools in time
  schemas      every tool name is valid and unique; input and output schemas are valid JSON Schema
  descriptions tool descriptions carry no hidden text or instructions aimed at the model (tool poisoning)
  annotations  tools say whether they are read-only or destructive, and the hints do not contradict each other
  stability    the tool list is the same on a second connection, and matches a lock file if one is given (rug pull):
               definitions, server name and version, launch command, image build, hosts it contacts
  pinning      the launch command names an exact version (npx pkg@1.2.3, uvx --from pkg==1.2.3, image@sha256)
  robustness   (opt-in, calls tools) invalid input is rejected cleanly and the server survives it
  isolation    whether the server ran in Zyven's sandbox (no network, read-only, no capabilities) or on this machine

Everything here is a pure function of an observation dict, so it is tested without starting a server.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"

NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")  # MCP tool names: 1-128 chars of letters, digits, _ - .
LONG_DESCRIPTION = 2000

# Text a tool description has no business containing: it speaks to the model, not about the tool.
INSTRUCTION_PATTERNS = [
    (r"ignore (all |any )?(previous|prior|above|other) (instructions|rules|prompts)", "tells the model to ignore its instructions"),
    (r"(do not|don't|never) (tell|mention|inform|reveal|show)( this)?( to)? (the )?user", "asks the model to hide something from the user"),
    (r"<\s*(important|system|instructions?|secret)\s*>", "hidden instruction block"),
    (r"\b(system prompt|developer message)\b", "talks about the model's system prompt"),
    (r"before (using|calling|running) (this|any|the) tool,? (you must |always )?(read|open|send|fetch|call|include)",
     "asks the model to do something else first"),
    (r"(~|\$home|%userprofile%)[/\\]\.(ssh|aws|config|gnupg)|id_rsa|\.npmrc|\.pypirc|mcp\.json|claude_desktop_config",
     "names a credential or config file"),
    (r"\b(api[_ -]?key|password|private key|access token|secret)s?\b.{0,60}\b(send|include|pass|add|append|post)\b",
     "asks for secrets to be passed along"),
    (r"\b(send|post|upload|forward|exfiltrate)\b.{0,80}https?://", "asks for data to be sent to a URL"),
    (r"(instead of|rather than) (using |calling )?(the )?\w+ tool", "tries to redirect calls meant for another tool"),
]
_INSTRUCTION_RES = [(re.compile(p, re.IGNORECASE | re.DOTALL), why) for p, why in INSTRUCTION_PATTERNS]
_BASE64_RE = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")
_BIDI = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}

# Terminal escape sequences. A CLI client that prints a tool description puts these straight on the screen, where they
# can hide text (SGR 8, colours), move the cursor and erase what was shown, plant a hyperlink whose text differs from
# its target (OSC 8) or write the clipboard (OSC 52). The model still reads every byte.
_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"   # OSC ... ended by BEL or ST
    r"|\x9d[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"    # 8-bit OSC
    r"|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"               # CSI (7- and 8-bit)
    r"|\x1b[PX^_][^\x1b\x9c]*(?:\x1b\\|\x9c)?"        # DCS, SOS, PM, APC strings
    r"|\x1b[ -/]*[0-~]"                               # any other escape
)
_CURSOR_FINALS = set("ABCDEFGHJKSTfsu")


def _ansi_findings(text: str) -> list[str]:
    kinds: dict[str, None] = {}  # insertion-ordered set
    concealed, links, hiding = [], [], False
    pos = 0
    for m in _ANSI_RE.finditer(text):
        if hiding:
            concealed.append(text[pos:m.start()])
        pos = m.end()
        seq = m.group(0)
        body = seq[2:] if seq.startswith("\x1b") else seq[1:]
        if seq.startswith(("\x1b]", "\x9d")):
            num, _, rest = body.rstrip("\x07\x9c").removesuffix("\x1b\\").partition(";")
            if num == "8":
                links.append(rest.partition(";")[2] or "(end of link)")
                kinds["hyperlinks (the text shown can differ from where the link goes)"] = None
            elif num == "52":
                kinds["writes the clipboard (OSC 52)"] = None
            elif num in ("0", "1", "2"):
                kinds["sets the terminal title"] = None
            else:
                kinds[f"operating system command OSC {num or '?'}"] = None
        elif seq.startswith(("\x1b[", "\x9b")):
            final, params = seq[-1], [p for p in seq[2 if seq.startswith("\x1b") else 1:-1].split(";")]
            if final == "m":
                if "8" in params:
                    hiding = True
                    kinds["concealed text (SGR 8)"] = None
                if any(p in ("0", "", "28") for p in params) and "8" not in params:
                    hiding = False
                kinds["colour or style changes (text can be drawn invisible against the background)"] = None
            elif final in _CURSOR_FINALS:
                kinds["cursor movement or erasing (can overwrite what was shown)"] = None
            else:
                kinds[f"control sequence ending in {final!r}"] = None
        else:
            kinds["other escape sequences"] = None
    if hiding:
        concealed.append(text[pos:])
    if not kinds:
        return []
    detail = "; ".join(kinds)
    hidden = "".join(concealed).strip()
    if hidden:
        detail += f"; concealed text reads: \"{hidden[:120]}\""
    real = [l for l in links if l != "(end of link)"]
    if real:
        detail += f"; links go to: {real[:3]}"
    return [f"terminal escape sequences: {detail}"]


def strip_hidden(text: str) -> str:
    """What the text says once escape sequences and invisible format characters are removed: instruction patterns are
    matched on this too, so `ign<ESC>[0more previous instructions` cannot slip past them."""
    text = _ANSI_RE.sub("", text)
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc") or ch in "\t\n\r")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    findings: list[str] = field(default_factory=list)
    failing: int = 0  # the first `failing` findings are failures, the rest warnings


@dataclass
class Report:
    target: str
    verdict: str  # PASS (maybe with warnings) or FAIL
    checks: list[Check]
    server: dict[str, Any]
    tools: list[str]
    lock: dict[str, str]  # tool name -> definition hash, for --lock
    launch: dict[str, Any] = field(default_factory=dict)  # command or URL, and the image build, for --lock
    reached_hosts: list[str] | None = None  # hosts reached through the egress proxy (None: not observed)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "checks": [asdict(c) for c in self.checks]}


class DefinitionsChanged(Exception):
    """A connected server now offers tool definitions the user did not review (a rug pull, or an update)."""

    def __init__(self, server: str, changed: list[str], added: list[str]) -> None:
        self.changed, self.added = changed, added
        parts = ([f"changed: {', '.join(changed)}"] if changed else []) + ([f"new: {', '.join(added)}"] if added else [])
        super().__init__(f"{server}: its tool definitions differ from the ones you approved ({'; '.join(parts)}). "
                         "It was not loaded. Open Connections and press Test to review the new definitions.")


def pin_diff(tools: list[dict[str, Any]], pins: dict[str, str]) -> tuple[list[str], list[str]]:
    """(changed, added) against the hashes recorded when the user tested the server; removed tools are harmless."""
    now = {t.get("name", ""): tool_hash(t) for t in tools}
    return sorted(n for n in now if n in pins and now[n] != pins[n]), sorted(n for n in now if n not in pins)


def tool_hash(tool: dict[str, Any]) -> str:
    """A tool's definition as the model sees it: name, description, schemas, annotations."""
    keep = {k: tool.get(k) for k in ("name", "title", "description", "inputSchema", "outputSchema", "annotations")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def hidden_characters(text: str) -> list[str]:
    """Characters that a person reading the description cannot see but a model reads."""
    found = []
    tags = [ch for ch in text if 0xE0000 <= ord(ch) <= 0xE007F]
    if tags:  # tag characters mirror ASCII, so the hidden message can be read back
        hidden = "".join(chr(ord(c) - 0xE0000) for c in tags if 0x20 <= ord(c) - 0xE0000 < 0x7F)
        found.append(f"{len(tags)} invisible Unicode tag characters; hidden text reads: \"{hidden[:120]}\"")
    bidi = sorted({f"U+{ord(ch):04X}" for ch in text if ch in _BIDI})
    if bidi:
        found.append(f"bidirectional override characters (text can display differently from what it says): {bidi}")
    other = sorted({f"U+{ord(ch):04X}" for ch in text if unicodedata.category(ch) == "Cf" and ch not in _BIDI
                    and ch != "­" and not 0xE0000 <= ord(ch) <= 0xE007F})
    if other:
        found.append(f"invisible format characters: {other}")
    found += _ansi_findings(text)
    controls = sorted({f"U+{ord(ch):04X}" for ch in _ANSI_RE.sub("", text)
                       if unicodedata.category(ch) == "Cc" and ch not in "\t\n\r"})
    if controls:
        found.append(f"control characters (backspace and the like can rewrite what is displayed): {controls}")
    return found


def scan_text(text: str) -> list[str]:
    out = hidden_characters(text)
    plain = strip_hidden(text)
    for rx, why in _INSTRUCTION_RES:
        m = rx.search(text) or rx.search(plain)
        if m:
            out.append(f"{why}: \"{m.group(0)[:80]}\"")
    if _BASE64_RE.search(text):
        out.append("contains a long base64-like blob")
    return out


def _schema_problems(schema: Any, where: str) -> list[str]:
    from jsonschema import exceptions, validators
    if not isinstance(schema, dict):
        return [f"{where} is not an object"]
    try:
        validators.validator_for(schema, default=validators.Draft202012Validator).check_schema(schema)
    except exceptions.SchemaError as e:
        return [f"{where} is not valid JSON Schema: {e.message[:160]}"]
    out = []
    if where == "inputSchema":
        if schema.get("type") != "object":
            out.append("inputSchema type is not 'object'")
        props = schema.get("properties") or {}
        missing = [r for r in schema.get("required") or [] if r not in props]
        if missing:
            out.append(f"required parameters not defined in properties: {missing}")
    return out


def _texts(tool: dict[str, Any]) -> list[tuple[str, str]]:
    """Every piece of text the model will read for this tool, with where it came from."""
    out = [("description", tool.get("description") or ""), ("title", tool.get("title") or "")]
    props = (tool.get("inputSchema") or {}).get("properties") or {}
    for pname, p in props.items() if isinstance(props, dict) else []:
        if isinstance(p, dict):
            out.append((f"parameter {pname}", f"{pname} {p.get('description') or ''} {p.get('title') or ''}"))
    return [(w, t) for w, t in out if t.strip()]


def run_checks(obs: dict[str, Any], lock: dict[str, str] | None = None,
               locked: dict[str, Any] | None = None) -> Report:
    """`lock` holds the pinned tool hashes; `locked` is the whole lock file (server, launch, hosts), if any."""
    from zyven.mcpverify.pinning import launch_of, lock_differences, reached_hosts, unpinned
    checks: list[Check] = []
    tools: list[dict[str, Any]] = obs.get("tools") or []
    names = [t.get("name", "") for t in tools]

    # handshake
    if not obs.get("started"):
        checks.append(Check("handshake", FAIL, f"server did not start or answer: {obs.get('error') or 'unknown error'}"))
        return Report(obs.get("target", ""), FAIL, checks, obs.get("server") or {}, [], {})
    srv = obs.get("server") or {}
    checks.append(Check("handshake", PASS if tools else WARN,
                        f"{' '.join(x for x in (srv.get('name') or 'server', srv.get('version')) if x)} "
                        f"(protocol {srv.get('protocol') or '?'}) "
                        f"listed {len(tools)} tools in {obs.get('seconds', 0):.1f}s"
                        + ("" if tools else "; it offers no tools")))

    # schemas
    bad: list[str] = []
    warn: list[str] = []
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        bad.append(f"duplicate tool names: {dupes}")
    for t in tools:
        n = t.get("name", "")
        if not NAME_RE.fullmatch(n):
            bad.append(f"{n!r}: name is not 1-128 letters, digits, '_', '-' or '.'")
        bad += [f"{n}: {p}" for p in _schema_problems(t.get("inputSchema"), "inputSchema")]
        if t.get("outputSchema") is not None:
            bad += [f"{n}: {p}" for p in _schema_problems(t.get("outputSchema"), "outputSchema")]
        props = (t.get("inputSchema") or {}).get("properties") or {}
        undocumented = [p for p, v in props.items() if isinstance(v, dict) and not v.get("description")] \
            if isinstance(props, dict) else []
        if undocumented:
            warn.append(f"{n}: parameters without a description: {undocumented}")
    checks.append(Check("schemas", FAIL if bad else (WARN if warn else PASS),
                        f"{len(bad)} problems" if bad else (f"valid; {len(warn)} tools with undocumented parameters"
                                                             if warn else f"{len(tools)} tool schemas valid"),
                        bad + warn, len(bad)))

    # descriptions (tool poisoning)
    bad, warn = [], []
    for t in tools:
        n = t.get("name", "")
        if not (t.get("description") or "").strip():
            warn.append(f"{n}: no description (the model has to guess what it does)")
        elif len(t["description"]) > LONG_DESCRIPTION:
            warn.append(f"{n}: description is {len(t['description'])} characters (unusually long; read it)")
        for where, text in _texts(t):
            bad += [f"{n} ({where}): {f}" for f in scan_text(text)]
    if obs.get("instructions"):
        bad += [f"server instructions: {f}" for f in scan_text(obs["instructions"])]
    checks.append(Check("descriptions", FAIL if bad else (WARN if warn else PASS),
                        f"{len(bad)} suspicious passages" if bad else
                        ("no hidden text or model-directed instructions found" + (f"; {len(warn)} notes" if warn else "")),
                        bad + warn, len(bad)))

    # annotations
    bad, warn = [], []
    for t in tools:
        n, ann = t.get("name", ""), t.get("annotations") or {}
        ro, destr = ann.get("readOnlyHint"), ann.get("destructiveHint")
        if ro is True and destr is True:
            bad.append(f"{n}: marked both read-only and destructive")
        if ro is None:
            warn.append(f"{n}: no readOnlyHint (clients must treat it as able to change things)")
    unmarked = sum(1 for t in tools if (t.get("annotations") or {}).get("readOnlyHint") is None)
    checks.append(Check("annotations", FAIL if bad else (WARN if warn else PASS),
                        "; ".join(bad) if bad else (f"{unmarked}/{len(tools)} tools do not say whether they are read-only"
                                                    if warn else "every tool says whether it is read-only"),
                        bad + warn, len(bad)))

    # stability
    hashes = {t.get("name", ""): tool_hash(t) for t in tools}
    again = obs.get("tools_again")
    bad, warn = [], []
    if again is not None:
        h2 = {t.get("name", ""): tool_hash(t) for t in again}
        changed = sorted(n for n in hashes.keys() & h2.keys() if hashes[n] != h2[n])
        if changed or set(hashes) != set(h2):
            bad.append(f"the tool list changed between two connections: changed {changed}, "
                       f"added {sorted(set(h2) - set(hashes))}, removed {sorted(set(hashes) - set(h2))}")
    if lock:
        changed = sorted(n for n in hashes.keys() & lock.keys() if hashes[n] != lock[n])
        if changed:
            bad.append(f"definitions differ from the lock file (re-read them before trusting): {changed}")
        removed, added = sorted(set(lock) - set(hashes)), sorted(set(hashes) - set(lock))
        if removed:
            warn.append(f"tools in the lock file but no longer offered: {removed}")
        if added:
            warn.append(f"new tools since the lock file: {added}")
    if locked:
        b, w = lock_differences(obs, locked)
        bad += b
        warn += w
    if again is None and obs.get("second_connection_error"):  # say why, instead of a silent skip
        warn.append(f"a second connection failed, so stability was not checked: {obs['second_connection_error']}")
    detail = ("tool definitions differ" if bad else
              ("same definitions on a second connection" if again is not None else
               ("second connection failed" if obs.get("second_connection_error") else "not checked twice"))
              + ("; matches the lock file" if (lock or locked) and not bad and not warn else ""))
    checks.append(Check("stability", FAIL if bad else (WARN if warn else (PASS if again is not None else SKIP)),
                        detail, bad + warn, len(bad)))

    # robustness (only when probes ran)
    probes = obs.get("probes")
    if probes is None:
        checks.append(Check("robustness", SKIP, "not run (pass --probe to call tools with invalid input)"))
    else:
        failed = [f"{p['tool']}: {p['detail']}" for p in probes if not p.get("ok")]
        rejected = len(probes) - len(failed)
        alive = obs.get("alive_after_probes")
        if alive is False:
            failed.append("server stopped answering after the probes")
        detail = (f"{rejected}/{len(probes)} invalid calls rejected cleanly" if probes
                  else "no tool has required parameters to leave out")
        checks.append(Check("robustness", FAIL if failed else PASS,
                            detail + ("; server still answering" if alive else ""), failed, len(failed)))

    # pinning (stdio servers: is the code that runs fixed by the command?)
    command = (obs.get("launch") or {}).get("command")
    if command:
        why = unpinned(command)
        checks.append(Check("pinning", WARN if why else PASS,
                            "the launch command can run a different release next time" if why else
                            "the launch command names exact versions", why))

    # isolation
    eg = obs.get("egress")
    if obs.get("sandboxed") and eg:
        refused = sorted({f"{d.get('host')}:{d.get('port')}" for d in eg.get("decisions", []) if not d.get("allowed")})
        used = sorted({d.get("host") for d in eg.get("decisions", []) if d.get("allowed")})
        checks.append(Check("isolation", WARN if refused else PASS,
                            f"ran in Zyven's sandbox with network limited to {', '.join(eg['hosts'])} (egress proxy)"
                            + (f"; reached {', '.join(used)}" if used else "; no connection made")
                            + (f"; REFUSED {len(refused)} other host(s)" if refused else ""),
                            [f"tried to reach {h}, which is not on the allowlist (refused)" for h in refused]))
    elif obs.get("sandboxed") and obs.get("network"):
        checks.append(Check("isolation", WARN, "ran in Zyven's sandbox (read-only root, no capabilities, non-root) "
                                               "but WITH network access (--allow-network)"))
    else:
        checks.append(Check("isolation", PASS if obs.get("sandboxed") else WARN,
                            "ran in Zyven's sandbox: no network, read-only root, no capabilities, non-root"
                            if obs.get("sandboxed") else
                            "ran on this machine with your permissions (use --docker IMAGE to run it in the sandbox)"))

    verdict = FAIL if any(c.status == FAIL for c in checks) else PASS
    return Report(obs.get("target", ""), verdict, checks, srv, names, hashes, launch_of(obs),
                  reached_hosts(obs) if obs.get("egress") else None)
