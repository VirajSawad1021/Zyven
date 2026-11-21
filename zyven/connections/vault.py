"""Where connection secrets live: an encrypted file whose key is kept in the operating system's keychain.

API keys and OAuth tokens used to sit in a plain JSON file, and on Windows the file mode protects nothing. The
keychain itself cannot hold them: Windows Credential Manager refuses a value of about 2.4 KB, and an OAuth token set is
often bigger. So the secrets are encrypted (Fernet: AES with an HMAC) into `connection-secrets.enc`, and only the
44-character key goes into the keychain (Windows Credential Manager, the macOS Keychain, the Secret Service on Linux).

Without a usable keychain (a headless Linux box, or ZYVEN_SECRETS=file) the plain file is kept, readable only by its
owner where the system allows that, and `backend` says so. An existing plain file is moved into the encrypted one the
first time it is read, and removed only after the encrypted copy reads back the same.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)
SERVICE = "zyven"


class SecretsLocked(RuntimeError):
    """The secrets are encrypted but their key is not in this keychain (another user, or the board was moved)."""


def _keyring():
    if os.environ.get("ZYVEN_SECRETS", "").lower() == "file":
        return None
    try:
        import keyring
        from keyring.backends import fail
        kr = keyring.get_keyring()
        return None if isinstance(kr, fail.Keyring) else kr
    except Exception:  # noqa: BLE001 - no keyring package or no backend: fall back to the plain file
        return None


class SecretFile:
    def __init__(self, directory: Path) -> None:
        self.plain = directory / "connection-secrets.json"
        self.enc = directory / "connection-secrets.enc"
        # one key per board folder, so two boards on one machine never share secrets
        self.account = "secrets-key:" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:16]

    @property
    def backend(self) -> str:
        return "keychain" if _keyring() is not None else "plain file"

    def _key(self, create: bool) -> bytes | None:
        kr = _keyring()
        if kr is None:
            return None
        try:
            key = kr.get_password(SERVICE, self.account)
            if key is None and create:
                from cryptography.fernet import Fernet
                key = Fernet.generate_key().decode()
                kr.set_password(SERVICE, self.account, key)
            return key.encode() if key else None
        except Exception as e:  # noqa: BLE001 - a locked or broken keychain: keep working with the plain file
            log.warning("keychain unavailable (%s); connection secrets stay in a plain file", type(e).__name__)
            return None

    def read(self) -> dict[str, Any]:
        if self.enc.exists():
            key = self._key(create=False)
            if key is None:
                raise SecretsLocked(f"connection secrets in {self.enc} are encrypted, but their key is not in this "
                                    "keychain (was the board folder moved, or is this another user?)")
            from cryptography.fernet import Fernet
            return json.loads(Fernet(key).decrypt(self.enc.read_bytes()))
        try:
            data = json.loads(self.plain.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if data:
            self._migrate(data)
        return data

    def write(self, data: dict[str, Any]) -> None:
        key = self._key(create=True)
        if key is None:
            self._write_plain(data)
            return
        from cryptography.fernet import Fernet
        tmp = self.enc.with_suffix(".tmp")
        tmp.write_bytes(Fernet(key).encrypt(json.dumps(data).encode()))
        tmp.replace(self.enc)
        if self.plain.exists():
            self.plain.unlink()

    def _migrate(self, data: dict[str, Any]) -> None:
        if self._key(create=True) is None:
            return
        plain = self.plain.read_bytes()
        self.write(data)  # also removes the plain file
        try:
            same = self.read() == data
        except Exception:  # noqa: BLE001
            same = False
        if not same:  # never lose a sign-in: put the plain file back and stop using the encrypted one
            self.plain.write_bytes(plain)
            self.enc.unlink(missing_ok=True)
            log.warning("could not verify the encrypted copy of %s; kept the plain file", self.plain)

    def _write_plain(self, data: dict[str, Any]) -> None:
        tmp = self.plain.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # best effort: a no-op for group/other bits on Windows
        except OSError:
            pass
        tmp.replace(self.plain)
