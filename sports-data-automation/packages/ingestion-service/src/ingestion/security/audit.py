"""
Security audit logging for the ingestion service.

WHAT: A small, structured logger for security-relevant events: authentication
    failures, rate-limit hits, request rejections (oversized / invalid), and
    access to protected endpoints. Each event is emitted as a single log line
    with stable fields (event, timestamp, client, path, outcome, detail).
WHY: Without audit events there is no way to detect brute-force attempts,
    replay attacks, or abusive clients, and no forensic trail after an incident.
    Keeping audit logging separate from business logging makes it easy to ship to
    a SIEM or log backend later.
WHEN: Call log_auth_failure() when an API key is missing/invalid,
    log_rate_limit() when a client is throttled, and log_rejection() when a
    request is rejected for size or validation reasons.
LANGUAGE: Python 3.11+. Stdlib logging only. No secrets are ever written to the
    audit log (client identifiers are hashed/redacted via security.secrets.redact).
"""

from __future__ import annotations

import logging
from typing import Optional

from ingestion.security.secrets import redact

logger = logging.getLogger("ingestion.security")

# Security event names (stable so log-based alerting can match on them).
EVENT_AUTH_FAILURE = "auth.failure"
EVENT_RATE_LIMIT = "rate.limit"
EVENT_REQUEST_REJECTED = "request.rejected"
EVENT_PROTECTED_ACCESS = "protected.access"


def _client_label(client_key: Optional[str], authenticated: bool) -> str:
    """Return a redacted client identifier for audit logs."""
    if not client_key:
        return "anonymous"
    # Authenticated clients are identified by a redacted API key; anonymous
    # clients are identified by their (already opaque) IP hash elsewhere.
    return redact(client_key) if authenticated else f"ip:{redact(client_key)}"


def log_auth_failure(
    client_key: Optional[str] = None,
    path: str = "",
    reason: str = "missing_or_invalid_api_key",
) -> None:
    """Log a failed authentication attempt on a protected endpoint."""
    logger.warning(
        "security.event event=%s client=%s path=%s outcome=denied reason=%s",
        EVENT_AUTH_FAILURE,
        _client_label(client_key, authenticated=bool(client_key)),
        path,
        reason,
    )


def log_rate_limit(client_key: str, authenticated: bool, path: str) -> None:
    """Log a client being throttled by the rate limiter."""
    logger.warning(
        "security.event event=%s client=%s path=%s outcome=rate_limited",
        EVENT_RATE_LIMIT,
        _client_label(client_key, authenticated),
        path,
    )


def log_rejection(
    client_key: Optional[str] = None,
    authenticated: bool = False,
    path: str = "",
    reason: str = "",
    detail: str = "",
) -> None:
    """Log a rejected request (oversized body, invalid input, etc.)."""
    logger.warning(
        "security.event event=%s client=%s path=%s outcome=rejected reason=%s detail=%s",
        EVENT_REQUEST_REJECTED,
        _client_label(client_key, authenticated),
        path,
        reason,
        detail,
    )


def log_protected_access(client_key: str, authenticated: bool, path: str) -> None:
    """Log a successful access to a protected endpoint (audit trail)."""
    logger.info(
        "security.event event=%s client=%s path=%s outcome=allowed",
        EVENT_PROTECTED_ACCESS,
        _client_label(client_key, authenticated),
        path,
    )
