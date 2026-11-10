"""
Security response headers middleware.

WHAT: A Starlette BaseHTTPMiddleware that appends a hardened set of security
    headers to every response: X-Content-Type-Options, X-Frame-Options,
    Referrer-Policy, Content-Security-Policy, X-XSS-Protection, and optionally
    Strict-Transport-Security (only when HSTS is enabled, for HTTPS deployments).
WHY: Defense-in-depth at the response layer. These headers tell clients to refuse
    MIME-type sniffing, disallow framing (clickjacking), restrict referrer
    leakage, and limit executable content — important because the ingestion
    service is a public-facing API.
WHEN: Add SecurityHeadersMiddleware to the FastAPI app (after CORS so both sets
    of headers coexist). Set HSTS only when the service is served over HTTPS in
    production; leave it off for local HTTP dev.
LANGUAGE: Python 3.11+. Starlette/FastAPI only.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Append security headers to every response."""

    def __init__(self, app, enabled: bool = True, hsts_enabled: bool = False, hsts_max_age: int = 31536000):
        super().__init__(app)
        self.enabled = enabled
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age = int(hsts_max_age)

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if not self.enabled:
            return response

        headers = response.headers
        # Prevent MIME-type sniffing (IE/Chrome): forces the browser to honor Content-Type.
        headers.setdefault("X-Content-Type-Options", "nosniff")
        # Disallow framing from any origin (clickjacking protection).
        headers.setdefault("X-Frame-Options", "DENY")
        # Limit referrer information sent to external sites.
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Older XSS filter (defense in depth; CSP is the modern control).
        headers.setdefault("X-XSS-Protection", "1; mode=block")
        # Restrictive CSP for a JSON API: no inline scripts, only same-origin.
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none';",
        )
        # HSTS only when served over HTTPS in production; enabling on plain HTTP
        # can cause browsers to refuse future plain-HTTP connections.
        if self.hsts_enabled:
            headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={self.hsts_max_age}; includeSubDomains",
            )
        return response
