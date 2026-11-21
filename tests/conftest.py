"""Shared test settings."""

import os

# Tests never touch the real keychain: connection secrets stay in plain files under each test's tmp folder.
# tests/test_vault.py sets up an in-memory keychain to test the encrypted path.
os.environ.setdefault("ZYVEN_SECRETS", "file")
