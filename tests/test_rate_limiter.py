"""
Unit tests for the token-bucket rate limiter (ingestion.security.rate_limiter).

These tests exercise TokenBucket and RateLimiter directly without FastAPI or Redis,
so they run fast and deterministically (time is advanced via monkeypatching
time.monotonic where needed).
"""

from __future__ import annotations

import time

import pytest

from ingestion.security.rate_limiter import RateLimiter, TokenBucket


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_bucket_allows_up_to_capacity_then_rejects():
    bucket = TokenBucket(capacity=3, refill_rate_per_second=10.0)
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    assert bucket.consume(1) is True
    assert bucket.consume(1) is False  # exhausted


def test_bucket_refills_over_time(monkeypatch):
    bucket = TokenBucket(capacity=1, refill_rate_per_second=10.0)  # 1 token / 0.1s
    assert bucket.consume(1) is True
    assert bucket.consume(1) is False  # exhausted now
    # Advance time by 0.2s -> 2 tokens refilled, capped at capacity 1.
    # Capture the real monotonic clock so the lambda does not recurse into itself.
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 0.2)
    assert bucket.consume(1) is True  # refilled
    assert bucket.consume(1) is False  # exhausted again


def test_retry_after_zero_when_tokens_available():
    bucket = TokenBucket(capacity=5, refill_rate_per_second=10.0)
    assert bucket.retry_after() == 0.0


def test_retry_after_positive_when_exhausted(monkeypatch):
    bucket = TokenBucket(capacity=1, refill_rate_per_second=10.0)  # 0.1s per token
    bucket.consume(1)
    # Advance just under 0.1s -> still need a fraction of a second
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 0.05)
    assert bucket.retry_after() > 0
    assert bucket.retry_after() < 0.1


def test_bucket_capacity_must_be_positive():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0, refill_rate_per_second=1.0)
    with pytest.raises(ValueError):
        TokenBucket(capacity=1, refill_rate_per_second=0.0)


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


@pytest.fixture
def limiter():
    # Auth: 60 rpm / burst 2  -> refill 1/s, cap 2
    # Anonymous: 10 rpm / burst 1 -> refill 1/6s, cap 1
    return RateLimiter(
        requests_per_minute=60,
        burst=2,
        anonymous_requests_per_minute=10,
        anonymous_burst=1,
    )


def test_authenticated_client_allows_burst_then_rate_limits(limiter):
    key = "user-key-1"
    assert limiter.allow(key, authenticated=True)[0] is True
    assert limiter.allow(key, authenticated=True)[0] is True  # burst
    allowed, retry = limiter.allow(key, authenticated=True)  # exhausted
    assert allowed is False
    assert retry > 0


def test_anonymous_client_has_lower_allowance(limiter):
    # Anonymous burst = 1
    assert limiter.allow("ip-1", authenticated=False)[0] is True
    allowed, _ = limiter.allow("ip-1", authenticated=False)
    assert allowed is False


def test_different_clients_have_independent_buckets(limiter):
    assert limiter.allow("client-a", authenticated=True)[0] is True
    assert limiter.allow("client-b", authenticated=True)[0] is True


def test_allow_returns_retry_after_when_limited(limiter):
    limiter.allow("k", authenticated=False)  # exhaust anon burst (1)
    allowed, retry = limiter.allow("k", authenticated=False)
    assert allowed is False
    assert retry > 0


def test_reset_clears_bucket(limiter):
    limiter.allow("k", authenticated=True)
    limiter.allow("k", authenticated=True)  # exhaust (burst 2)
    limiter.reset("k")
    assert limiter.allow("k", authenticated=True)[0] is True


def test_reset_none_clears_all(limiter):
    limiter.allow("a", authenticated=True)
    limiter.allow("b", authenticated=True)
    limiter.reset()
    assert limiter.allow("a", authenticated=True)[0] is True
    assert limiter.allow("b", authenticated=True)[0] is True
