"""
Tests for SecurityHeadersMiddleware (ingestion.security.headers).

Uses FastAPI's TestClient to assert the expected security headers are present on
responses, and that HSTS is opt-in (off by default, on when configured).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion.security.headers import SecurityHeadersMiddleware

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-xss-protection": "1; mode=block",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none';",
}


def _make_app(hsts_enabled: bool = False) -> TestClient:
    app = FastAPI()

    @app.get("/")
    async def root():
        return {"ok": True}

    app.add_middleware(
        SecurityHeadersMiddleware,
        enabled=True,
        hsts_enabled=hsts_enabled,
        hsts_max_age=31536000,
    )
    return TestClient(app)


def test_security_headers_present():
    client = _make_app(hsts_enabled=False)
    response = client.get("/")
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers[name] == value, f"missing/incorrect header {name}"


def test_hsts_absent_by_default():
    client = _make_app(hsts_enabled=False)
    assert "strict-transport-security" not in client.get("/").headers


def test_hsts_present_when_enabled():
    client = _make_app(hsts_enabled=True)
    hsts = client.get("/").headers.get("strict-transport-security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
