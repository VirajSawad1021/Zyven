"""Connections: MCP servers a user connects to (a hosted URL, or a local command), with local secret storage.

Public metadata lives in `connections.json`; tokens and API keys live in a separate `connection-secrets.json`
that is never returned by the API, never sent to the browser after it is entered, and never shown to a model.
Both files sit in the board directory, which is git-ignored.

Local-command (stdio) connectors run code on this machine with the user's permissions, so they are refused
unless ZYVEN_ALLOW_STDIO_CONNECTORS=1: a web page that can reach the local board must not be able to start a
process by adding a connector.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

NAME = re.compile(r"[\w .\-]{1,60}")
SECRET_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{0,63}")


class ConnectionError_(ValueError):
    """A connection was refused or is malformed; the message is safe to show the user."""


def stdio_allowed() -> bool:
    return os.environ.get("ZYVEN_ALLOW_STDIO_CONNECTORS") == "1"


def _check_url(url: str) -> str:
    if re.fullmatch(r"https://[^\s/]+(/\S*)?", url):
        return url
    if re.fullmatch(r"http://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(/\S*)?", url):  # plain http only for this machine
        return url
    raise ConnectionError_("the URL must be https (plain http is accepted only for localhost)")


class ConnectionStore:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory) / "connections"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._meta = self.dir / "connections.json"
        self._secrets = self.dir / "connection-secrets.json"
        self._lock = threading.Lock()

    # --- file helpers -------------------------------------------------------------------------------
    def _read(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, path: Path, data: dict[str, Any], private: bool = False) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        if private:
            try:
                os.chmod(tmp, 0o600)  # best effort: a no-op for group/other bits on Windows
            except OSError:
                pass
        tmp.replace(path)

    # --- public API ---------------------------------------------------------------------------------
    def _public(self, cid: str, c: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
        mine = secrets.get(cid, {})
        out = {k: v for k, v in c.items()}
        out["id"] = cid
        out["secret_names"] = sorted(k for k in mine if not k.startswith("_"))  # names only, never values
        out["signed_in"] = "_oauth_tokens" in mine  # OAuth connections: do we hold a token
        return out

    def list(self) -> list[dict[str, Any]]:
        meta, secrets = self._read(self._meta), self._read(self._secrets)
        return [self._public(cid, c, secrets) for cid, c in meta.items()]

    def get(self, cid: str) -> dict[str, Any]:
        meta = self._read(self._meta)
        if cid not in meta:
            raise KeyError(cid)
        return self._public(cid, meta[cid], self._read(self._secrets))

    def add(self, *, name: str, kind: str, url: str = "", command: str = "", args: list[str] | None = None,
            secrets: dict[str, str] | None = None, oauth: bool = False, oauth_client_id: str = "",
            oauth_client_secret: str = "") -> dict[str, Any]:
        """kind "http": a hosted MCP server (secrets are sent as headers). kind "stdio": a local command
        (secrets are passed as environment variables). oauth=True (http only): the user signs in through the
        service's own page; a client id/secret is only needed when the service does not register apps itself."""
        name = name.strip()
        if not NAME.fullmatch(name):
            raise ConnectionError_("give the connection a short name")
        secrets = {k: v for k, v in (secrets or {}).items() if v}
        for k in secrets:
            if not SECRET_KEY.fullmatch(k):
                raise ConnectionError_(f"bad secret name {k!r}")
        if oauth and kind != "http":
            raise ConnectionError_("OAuth sign-in only applies to hosted (URL) connections")
        if oauth and secrets:
            raise ConnectionError_("an OAuth connection signs in through the service; it takes no pasted headers")
        if kind == "http":
            entry: dict[str, Any] = {"name": name, "kind": "http", "url": _check_url(url.strip()), "oauth": bool(oauth)}
        elif kind == "stdio":
            if not stdio_allowed():
                raise ConnectionError_("local-command connectors are off. They run code on this machine; "
                                       "set ZYVEN_ALLOW_STDIO_CONNECTORS=1 to allow them.")
            if not command.strip():
                raise ConnectionError_("a local connector needs a command")
            entry = {"name": name, "kind": "stdio", "command": command.strip(), "args": [str(a) for a in (args or [])]}
        else:
            raise ConnectionError_("kind must be http or stdio")
        entry.update({"enabled": False, "tools": None, "error": None, "checked": None})
        cid = uuid.uuid4().hex[:8]
        if oauth and (oauth_client_id or oauth_client_secret):
            if not oauth_client_id.strip():
                raise ConnectionError_("an OAuth client secret needs its client id")
            secrets = {"_oauth_client": json.dumps({"client_id": oauth_client_id.strip(),
                                                    "client_secret": oauth_client_secret or None})}
        with self._lock:
            meta, sec = self._read(self._meta), self._read(self._secrets)
            meta[cid] = entry
            if secrets:
                sec[cid] = secrets
            self._write(self._meta, meta)
            self._write(self._secrets, sec, private=True)
        return self.get(cid)

    def update(self, cid: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            meta = self._read(self._meta)
            if cid not in meta:
                raise KeyError(cid)
            meta[cid].update(fields)
            self._write(self._meta, meta)
        return self.get(cid)

    def set_enabled(self, cid: str, enabled: bool) -> dict[str, Any]:
        c = self.get(cid)
        if enabled and c["tools"] is None:
            raise ConnectionError_("test the connection first so you can see what it can do")
        return self.update(cid, enabled=enabled)

    def remove(self, cid: str) -> None:
        with self._lock:
            meta, sec = self._read(self._meta), self._read(self._secrets)
            if cid not in meta:
                raise KeyError(cid)
            meta.pop(cid)
            sec.pop(cid, None)
            self._write(self._meta, meta)
            self._write(self._secrets, sec, private=True)

    def set_secret(self, cid: str, key: str, value: str) -> None:
        with self._lock:
            sec = self._read(self._secrets)
            sec.setdefault(cid, {})[key] = value
            self._write(self._secrets, sec, private=True)

    def delete_secret(self, cid: str, key: str) -> None:
        with self._lock:
            sec = self._read(self._secrets)
            if sec.get(cid, {}).pop(key, None) is not None:
                self._write(self._secrets, sec, private=True)

    def secret(self, cid: str, key: str) -> str | None:
        return self._read(self._secrets).get(cid, {}).get(key)

    def secrets_for(self, cid: str) -> dict[str, str]:
        """Internal: the values, for launching or calling the server. Never expose this over the API."""
        return dict(self._read(self._secrets).get(cid, {}))
