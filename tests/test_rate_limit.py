"""Tests del rate limiting (protección del cómputo del plan gratis)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from doc2md.adapters.inbound import rate_limit
from doc2md.adapters.inbound.http import _client_ip, app

client = TestClient(app)

TXT = {"files": ("nota.txt", b"hola mundo", "text/plain")}


@pytest.fixture(autouse=True)
def _clean_limiter():
    """Estado limpio antes y después de cada test de este módulo."""
    rate_limit.reset()
    yield
    rate_limit.reset()


def test_per_ip_limit_returns_429(monkeypatch):
    monkeypatch.setattr(rate_limit, "PER_IP", 3)
    monkeypatch.setattr(rate_limit, "GLOBAL", 1000)

    for _ in range(3):
        assert client.post("/convert", files=TXT).status_code == 200

    r = client.post("/convert", files=TXT)
    assert r.status_code == 429
    assert r.json()["code"] == "INFRA_RATE_LIMITED"
    assert "Retry-After" in r.headers
    assert int(r.headers["Retry-After"]) >= 1


def test_global_limit_returns_429(monkeypatch):
    monkeypatch.setattr(rate_limit, "PER_IP", 1000)
    monkeypatch.setattr(rate_limit, "GLOBAL", 2)

    assert client.post("/convert", files=TXT).status_code == 200
    assert client.post("/convert", files=TXT).status_code == 200
    assert client.post("/convert", files=TXT).status_code == 429


def test_health_never_rate_limited(monkeypatch):
    monkeypatch.setattr(rate_limit, "PER_IP", 1)
    monkeypatch.setattr(rate_limit, "GLOBAL", 1)
    for _ in range(10):
        assert client.get("/health").status_code == 200


def test_disabled_flag_bypasses(monkeypatch):
    monkeypatch.setattr(rate_limit, "ENABLED", False)
    monkeypatch.setattr(rate_limit, "PER_IP", 1)
    for _ in range(5):
        assert client.post("/convert", files=TXT).status_code == 200


def test_client_ip_prefers_forwarded_for():
    class _Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert _client_ip(_Req()) == "203.0.113.7"


def test_client_ip_fallback_to_peer():
    class _Req:
        headers: dict[str, str] = {}
        client = type("C", (), {"host": "192.0.2.5"})()

    assert _client_ip(_Req()) == "192.0.2.5"
