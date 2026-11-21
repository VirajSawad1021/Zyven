"""Connection secrets: encrypted with the key in the keychain, a plain file without one, and a safe migration."""

from __future__ import annotations

import json

import keyring
import pytest
from keyring.backend import KeyringBackend

from zyven.connections import vault
from zyven.connections.store import ConnectionStore


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        if len(password) > 1000:  # like Windows Credential Manager, which refuses about 2.4 KB
            raise RuntimeError("too big for this keychain")
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        self.items.pop((service, username), None)


@pytest.fixture
def chain(monkeypatch):
    monkeypatch.delenv("ZYVEN_SECRETS", raising=False)
    kr = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(previous)


BIG_TOKENS = json.dumps({"access_token": "a" * 3000, "refresh_token": "r" * 1500, "expires_in": 3600})


def test_secrets_are_encrypted_and_only_the_key_is_in_the_keychain(tmp_path, chain):
    store = ConnectionStore(tmp_path)
    c = store.add(name="Notion", kind="http", url="https://mcp.example.com/mcp", secrets={"API_KEY": "sk-123"})
    store.set_secret(c["id"], "_oauth_tokens", BIG_TOKENS)  # bigger than the keychain takes as one value
    files = {p.name for p in (tmp_path / "connections").iterdir()}
    assert "connection-secrets.enc" in files and "connection-secrets.json" not in files
    raw = (tmp_path / "connections" / "connection-secrets.enc").read_bytes()
    assert b"sk-123" not in raw and b"aaaa" not in raw
    assert list(chain.items) == [("zyven", store._vault.account)] and len(next(iter(chain.items.values()))) == 44
    again = ConnectionStore(tmp_path)  # a new process reads them back
    assert again.secret(c["id"], "API_KEY") == "sk-123" and again.secret(c["id"], "_oauth_tokens") == BIG_TOKENS
    assert "sk-123" not in json.dumps(again.list())  # names only, never values, as before


def test_a_plain_file_is_migrated_and_removed_only_after_it_reads_back(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_SECRETS", "file")
    old = ConnectionStore(tmp_path)
    c = old.add(name="Svc", kind="http", url="https://mcp.example.com/mcp", secrets={"TOKEN": "t-1"})
    plain = tmp_path / "connections" / "connection-secrets.json"
    assert plain.exists()
    monkeypatch.delenv("ZYVEN_SECRETS")
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    try:
        assert ConnectionStore(tmp_path).secret(c["id"], "TOKEN") == "t-1"
        assert not plain.exists() and (tmp_path / "connections" / "connection-secrets.enc").exists()
        assert ConnectionStore(tmp_path).secret(c["id"], "TOKEN") == "t-1"
    finally:
        keyring.set_keyring(keyring.backends.fail.Keyring())


def test_no_keychain_keeps_the_plain_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYVEN_SECRETS", "file")
    store = ConnectionStore(tmp_path)
    c = store.add(name="Svc", kind="http", url="https://mcp.example.com/mcp", secrets={"TOKEN": "t-1"})
    assert store._vault.backend == "plain file"
    assert (tmp_path / "connections" / "connection-secrets.json").exists()
    assert store.secret(c["id"], "TOKEN") == "t-1"


def test_encrypted_secrets_without_their_key_say_so(tmp_path, chain):
    store = ConnectionStore(tmp_path)
    store.add(name="Svc", kind="http", url="https://mcp.example.com/mcp", secrets={"TOKEN": "t-1"})
    chain.items.clear()  # another user, or the board folder moved
    with pytest.raises(vault.SecretsLocked, match="key is not in this keychain"):
        ConnectionStore(tmp_path).list()
