"""Security components for the ingestion service.

Modules:
    secrets    - secret redaction and dev-default detection
    audit      - structured security audit logging
    rate_limiter - token-bucket rate limiting + body size guard
    headers    - security response headers middleware
"""

from ingestion.security.audit import (
    EVENT_AUTH_FAILURE,
    EVENT_RATE_LIMIT,
    EVENT_REQUEST_REJECTED,
    EVENT_PROTECTED_ACCESS,
    log_auth_failure,
    log_rate_limit,
    log_rejection,
    log_protected_access,
)
from ingestion.security.headers import SecurityHeadersMiddleware
from ingestion.security.rate_limiter import RateLimiter, rate_limit_middleware
from ingestion.security.secrets import redact, contains_dev_default, mask_headers

__all__ = [
    "redact",
    "contains_dev_default",
    "mask_headers",
    "log_auth_failure",
    "log_rate_limit",
    "log_rejection",
    "log_protected_access",
    "EVENT_AUTH_FAILURE",
    "EVENT_RATE_LIMIT",
    "EVENT_REQUEST_REJECTED",
    "EVENT_PROTECTED_ACCESS",
    "SecurityHeadersMiddleware",
    "RateLimiter",
    "rate_limit_middleware",
]
