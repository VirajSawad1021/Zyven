"""The local-only guard: wrong Host and cross-site writes are refused; the board's own page and tools are not."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zyven.orchestrator.guard import allowed_hosts, check, install  # noqa: E402


@pytest.fixture
def client():
    app = FastAPI()
    install(app)

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.post("/api/change")
    def change():
        return {"changed": True}

    return TestClient(app, base_url="http://127.0.0.1:8765")


def test_the_board_s_own_requests_pass(client):
    assert client.get("/api/ping").status_code == 200
    r = client.post("/api/change", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert client.post("/api/change", headers={"Origin": "http://localhost:3000"}).status_code == 200  # the dev server
    assert client.post("/api/change").status_code == 200  # curl, scripts and tests send no Origin


@pytest.mark.parametrize("origin", ["https://evil.example", "http://127.0.0.1.evil.example", "null"])
def test_a_page_on_another_site_cannot_change_anything(client, origin):
    r = client.post("/api/change", headers={"Origin": origin})
    assert r.status_code == 403 and "must come from the board itself" in r.json()["detail"]


def test_a_foreign_host_name_is_refused_even_for_reads_dns_rebinding(client):
    r = client.get("/api/ping", headers={"Host": "attacker.example:8765"})
    assert r.status_code == 403 and "answers only on this machine" in r.json()["detail"]


def test_reads_from_another_origin_are_not_blocked_by_this_guard(client):
    assert client.get("/api/ping", headers={"Origin": "https://evil.example"}).status_code == 200  # browsers block the reply


def test_hosts_can_be_added_on_purpose(monkeypatch):
    monkeypatch.setenv("ZYVEN_ALLOWED_HOSTS", "zyven.lan, box")
    allowed = allowed_hosts()
    assert check("POST", "zyven.lan:8765", "http://zyven.lan:8765", allowed) is None
    assert check("GET", "other.lan", None, allowed) is not None
    assert check("GET", "[::1]:8765", None, allowed) is None
