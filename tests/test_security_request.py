"""
Integration tests for the security middleware stack as wired in ingestion.main.

Builds a standalone FastAPI app (no Redis, no lifespan) that mirrors main.py's
wiring: SecurityHeadersMiddleware on every response, plus a rate-limit + body-size
guard on /ingest/* and /dlq/*, with API-key authentication and audit logging on
the protected route. Runs through FastAPI's TestClient.
"""

from __future__ import annotations

import logging
from fastapi import FastAPI, Request, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from fastapi.testclient import TestClient

from ingestion.security import (
    RateLimiter,
    SecurityHeadersMiddleware,
    rate_limit_middleware,
    log_auth_failure,
)

API_KEY = "secret-key"
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _build_app(burst: int = 1, max_body_size: int = 50):
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enabled=True)

    limiter = RateLimiter(
        requests_per_minute=60,
        burst=burst,
        anonymous_requests_per_minute=10,
        anonymous_burst=1,
    )

    @app.middleware("http")
    async def security_mw(request: Request, call_next):
        return await rate_limit_middleware(
            request, call_next, limiter, enabled=True, max_body_size=max_body_size
        )

    async def verify_key(request: Request, api_key: str | None = Security(api_key_header)):
        if api_key != API_KEY:
            log_auth_failure(api_key, request.url.path, reason="missing_or_invalid_api_key")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
        return api_key

    @app.post("/ingest/event")
    async def ingest_event(request: Request, key: str = Depends(verify_key)):
        return {"ok": True, "key": key}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return TestClient(app), limiter


def test_authenticated_request_passes_then_rate_limits():
    client, _ = _build_app(burst=1)
    headers = {"X-API-Key": API_KEY}
    first = client.post("/ingest/event", json={"eventId": "e1"}, headers=headers)
    assert first.status_code == 200, first.text
    # Burst exhausted -> 429 with Retry-After
    second = client.post("/ingest/event", json={"eventId": "e2"}, headers=headers)
    assert second.status_code == 429, second.text
    assert "retry-after" in second.headers


def test_anonymous_requests_share_low_bucket():
    client, _ = _build_app(burst=1)
    # No API key -> authenticated=False, anonymous bucket (burst = 1).
    # First request passes the rate limiter, then auth returns 401.
    first = client.post("/ingest/event", json={"eventId": "e1"})
    assert first.status_code == 401
    # Second anonymous request exhausts the shared anon bucket -> 429 before auth runs.
    second = client.post("/ingest/event", json={"eventId": "e2"})
    assert second.status_code == 429, second.text
    assert "retry-after" in second.headers


def test_health_endpoint_not_rate_limited():
    client, _ = _build_app(burst=1)
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200


def test_oversized_body_rejected_413():
    client, _ = _build_app(max_body_size=50)
    headers = {"X-API-Key": API_KEY, "Content-Length": "200"}
    response = client.post("/ingest/event", headers=headers)
    assert response.status_code == 413, response.text


def test_security_headers_on_protected_response():
    client, _ = _build_app(burst=1)
    headers = {"X-API-Key": API_KEY}
    response = client.post("/ingest/event", json={"eventId": "e1"}, headers=headers)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in response.headers  # HSTS off by default


def test_auth_failure_is_audited(caplog):
    caplog.set_level(logging.WARNING, logger="ingestion.security")
    client, _ = _build_app(burst=1)
    response = client.post("/ingest/event", json={"eventId": "e1"})
    assert response.status_code == 401
    assert any("auth.failure" in record.getMessage() for record in caplog.records), caplog.text


def test_body_size_guard_skips_when_content_length_absent():
    client, _ = _build_app(max_body_size=50)
    headers = {"X-API-Key": API_KEY}
    # No content-length -> size guard skipped, auth runs -> 200
    response = client.post("/ingest/event", json={"eventId": "e1"}, headers=headers)
    assert response.status_code == 200
