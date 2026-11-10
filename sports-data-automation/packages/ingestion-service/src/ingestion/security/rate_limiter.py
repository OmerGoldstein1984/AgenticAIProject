"""
Token-bucket rate limiter for the ingestion service.

WHAT: A per-client token bucket that throttles write-heavy endpoints
    (/ingest/*, /dlq/*). Clients are identified by their X-API-Key when present
    (authenticated, higher allowance) or by client IP otherwise (anonymous,
    lower allowance). Each allowed request consumes one token; empty buckets are
    rejected with HTTP 429 and a Retry-After header.
WHY: Ingestion endpoints are public-facing and write-heavy. Without rate
    limiting a single client can exhaust Redis/n8n capacity, starve legitimate
    traders, or brute-force the API key. Token buckets allow short bursts (good
    for demo data injection) while enforcing a sustained ceiling.
WHEN: Instantiate RateLimiter from Settings and call allow(client_key,
    authenticated) inside an HTTP middleware; reject with 429 when it returns
    False.
LANGUAGE: Python 3.11+. Stdlib only. Not thread-safe by design (FastAPI/uvicorn
    runs one event loop per worker); each worker keeps its own buckets, which is
    acceptable for a single-node service and simple to reason about.
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class TokenBucket:
    """A single token bucket refilling at a fixed rate.

    Tokens accrue continuously up to `capacity`. consume(n) removes `n` tokens
    and returns True when sufficient tokens exist, False otherwise.
    """

    def __init__(self, capacity: int, refill_rate_per_second: float):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if refill_rate_per_second <= 0:
            raise ValueError("refill_rate_per_second must be > 0")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate_per_second)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_refill)
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume `tokens`; return True if allowed."""
        if tokens < 1:
            return True
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= float(tokens)
            return True
        return False

    def retry_after(self) -> float:
        """Seconds until at least one token is available (0 if already available)."""
        self._refill()
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class RateLimiter:
    """Per-client token-bucket rate limiter.

    Authenticated clients (present API key) use auth_capacity/auth_refill;
    anonymous clients use the smaller anonymous bucket. Buckets are keyed by
    client identifier and retained for the life of the process.
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        burst: int = 10,
        anonymous_requests_per_minute: int = 20,
        anonymous_burst: int = 5,
    ):
        self.auth_capacity = max(1, int(burst))
        self.auth_refill = max(0.1, float(requests_per_minute) / 60.0)
        self.anon_capacity = max(1, int(anonymous_burst))
        self.anon_refill = max(0.1, float(anonymous_requests_per_minute) / 60.0)
        self._buckets: Dict[str, TokenBucket] = {}

    def _bucket_for(self, key: str, authenticated: bool) -> TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            if authenticated:
                bucket = TokenBucket(capacity=self.auth_capacity, refill_rate_per_second=self.auth_refill)
            else:
                bucket = TokenBucket(capacity=self.anon_capacity, refill_rate_per_second=self.anon_refill)
            self._buckets[key] = bucket
        return bucket

    def allow(self, client_key: str, authenticated: bool) -> Tuple[bool, float]:
        """Return (allowed, retry_after_seconds) for `client_key`."""
        bucket = self._bucket_for(client_key, authenticated)
        if bucket.consume(1):
            return True, 0.0
        return False, bucket.retry_after()

    def reset(self, client_key: Optional[str] = None) -> None:
        """Drop bucket(s), mostly useful in tests. None clears all buckets."""
        if client_key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(client_key, None)


async def rate_limit_middleware(
    request,
    call_next,
    limiter: Optional[RateLimiter],
    enabled: bool = True,
    max_body_size: Optional[int] = None,
):
    """ASGI/Starlette-style middleware function: rate-limit and size-limit /ingest/* and /dlq/*.

    WHAT: Identifies the client from X-API-Key (authenticated) or client IP
        (anonymous), consults the token bucket, checks the request body size
        against max_body_size, and either short-circuits with a 429 (rate limit)
        or 413 (body too large) response, or continues the request. When the
        limiter is disabled or not configured the request passes through
        untouched. Reading Content-Length is a fast pre-flight guard; a proxy
        (or edge WAF) should enforce the same limit for defense in depth.
    WHY: Centralized throttle and size guard so all write endpoints share one
        policy without repeating logic in every route. Oversized bodies are a
        classic DoS vector against JSON APIs.
    INPUTS: request (Starlette Request), call_next, limiter (RateLimiter or None),
        enabled (bool), max_body_size (int bytes or None).
    OUTPUTS: a Response (429/413 when limited/rejected, otherwise call_next's response).
    """
    from starlette.responses import JSONResponse
    from ingestion.security.audit import log_rejection

    path = request.url.path
    if not enabled or limiter is None:
        return await call_next(request)
    if not (path.startswith("/ingest/") or path.startswith("/dlq/")):
        return await call_next(request)

    # Request body size guard (fast pre-flight via Content-Length header).
    if max_body_size is not None:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                length = 0
            if length > max_body_size:
                api_key = request.headers.get("x-api-key")
                authenticated = bool(api_key)
                client_key = (
                    api_key if authenticated else (request.client.host if request.client else "anonymous")
                )
                log_rejection(
                    client_key,
                    authenticated,
                    path,
                    reason="request_body_too_large",
                    detail=f"content_length={length} max={max_body_size}",
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "request_entity_too_large",
                        "detail": f"Request body exceeds {max_body_size} bytes.",
                    },
                )

    api_key = request.headers.get("x-api-key")
    authenticated = bool(api_key)
    client_key = api_key if authenticated else (request.client.host if request.client else "anonymous")

    allowed, retry_after = limiter.allow(client_key, authenticated)
    if not allowed:
        from ingestion.security.audit import log_rate_limit

        log_rate_limit(client_key, authenticated, path)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limit_exceeded",
                "detail": "Too many requests. Slow down and retry later.",
                "retry_after": round(retry_after, 2),
            },
            headers={"Retry-After": str(int(retry_after) + 1), "X-RateLimit-Limit": "exceeded"},
        )

    response = await call_next(request)
    try:
        response.headers["X-RateLimit-Remaining"] = "1"  # best-effort hint
    except Exception:  # pragma: no cover - defensive
        pass
    return response
