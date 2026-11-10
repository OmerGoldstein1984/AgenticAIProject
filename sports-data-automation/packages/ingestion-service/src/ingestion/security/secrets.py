"""
Secret handling helpers for the ingestion service.

WHAT: Small, dependency-free utilities for dealing with runtime secrets (API keys,
    database passwords, webhook URLs) without leaking them into logs or error
    responses, plus a detector for well-known development defaults that must never
    reach production.
WHY: Secrets compared or logged in plaintext end up in log files, error bodies,
    and metrics, where they can be read by anyone with log access. Dev-friendly
    defaults such as "changeme" silently reach production when `.env` is missing,
    creating well-known credentials.
WHEN: Call redact() before logging any secret-derived value; call
    contains_dev_default() at startup / in tests to assert no placeholder secrets
    are configured.
LANGUAGE: Python 3.11+. Stdlib only.
"""

from __future__ import annotations

# Well-known placeholder / development-default values that must never be used in
# a non-development environment. Matching is case-insensitive and substring-based
# so "changeme", "changeme123", "your-secret-here", etc. are all caught.
DEV_DEFAULT_MARKERS = (
    "changeme",
    "default",
    "placeholder",
    "your-",
    "example",
    "test",
    "demo",
    "admin",
    "password",
    "secret",
    "insert",
    "todo",
    "none",
    "null",
)


def redact(secret: str | None, show: int = 2) -> str:
    """Return a safely-loggable representation of a secret.

    WHAT: Shows only the first `show` and last `show` characters of a secret,
        replacing the middle with asterisks. Secrets shorter than 2*show+1
        characters are fully masked as "***". None/empty values become "[redacted]".
    WHY: Logs and error responses must never contain full secrets; a partially
        masked value is enough to confirm which key is in use without exposing it.
    INPUTS: secret (str or None), show (number of chars to reveal at each end).
    OUTPUTS: a masked string safe to write to logs.
    """
    if not secret:
        return "[redacted]"
    if len(secret) <= 2 * show + 1:
        return "***"
    return f"{secret[:show]}...{secret[-show:]}"


def contains_dev_default(value: str | None) -> bool:
    """Return True if `value` looks like a development default placeholder.

    WHAT: Case-insensitive substring check against DEV_DEFAULT_MARKERS. Empty or
        None values are not considered dev defaults (they are "not set", which is
        a separate concern handled by the Settings validator).
    WHY: Central, testable definition of what counts as a placeholder so the
        startup validator, tests, and docs all agree.
    INPUTS: value (str or None).
    OUTPUTS: bool.
    """
    if not value:
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in DEV_DEFAULT_MARKERS)


def mask_headers(headers: dict) -> dict:
    """Return a copy of an HTTP headers mapping with Authorization-ish headers masked.

    WHAT: Masks the value of any header whose name contains "authorization",
        "x-api-key", "cookie", or "set-cookie".
    WHY: Outbound/inbound request logging must not leak credentials.
    """
    sensitive = ("authorization", "x-api-key", "cookie", "set-cookie")
    masked: dict = {}
    for key, value in headers.items():
        if any(sensitive_name in key.lower() for sensitive_name in sensitive):
            masked[key] = redact(value)
        else:
            masked[key] = value
    return masked
