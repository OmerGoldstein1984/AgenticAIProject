"""
Deduplicator using Redis for idempotent processing.

FILE HEADER
-----------
Business problem this file solves:
    The same odds update or event can arrive multiple times (retry, reconnect replay, publisher
    redelivery). Processing it twice would double-count bets, break settlement, and corrupt
    analytics. Deduplicator guarantees at-least-once delivery becomes exactly-once processing by
    remembering each processed item's key in Redis with a TTL, so duplicates are detected and
    dropped before they reach n8n.

Where it sits in the flow:
    Inside the ingestion pipeline, between transformation and forwarding to n8n. main.py's
    process_odds/process_event/process_settlement call deduplicator.check_and_store(...) and skip
    forwarding when it reports a duplicate.

What calls it / what it calls:
    Called by: main.py process_odds/process_event/process_settlement.
    Calls: Redis (redis.asyncio) for SET NX EX and other commands.
What breaks if removed:
    No dedup → every replay/retry is processed twice; downstream n8n nodes and settlement would
    act on duplicate odds/events, producing wrong payouts and inflated metrics.
Language conventions:
    Python 3.11+. redis.asyncio async client. SET NX EX for atomic check-and-set with TTL.
    Three dedup strategies implemented (Deduplicator, SlidingWindowDeduplicator,
    BloomFilterDeduplicator); only Deduplicator is actually wired in main.py.
GAP: SlidingWindowDeduplicator and BloomFilterDeduplicator are defined but unused (dead code).
    main.py hard-codes Deduplicator. See 07_issues_found.md.
"""
import logging
from typing import Optional
import redis.asyncio as redis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class Deduplicator:
    """Redis-based deduplicator with TTL expiration.

    WHAT: check_and_store(key) atomically sets key→"1" with NX (only-if-not-exists) and a TTL;
        returns True if the key already existed (duplicate), False if it was newly stored.
    WHY: Provides idempotent processing — the same odds/event/settlement key is processed once
        within the TTL window (24h default), then forgotten so a legitimately updated value can
        eventually be re-processed.
    INPUTS (constructor): redis_url, ttl_seconds (default 86400 = 24h), key_prefix ("dedup:").
        check_and_store(key) input: the dedup key string.
    OUTPUTS: check_and_store returns bool — True = duplicate (skip), False = new (process).
    SIDE EFFECTS: writes to Redis; connects/disconnects from Redis.
    FAILURE MODES: if Redis is down, check_and_store logs the error and returns False
        (allow-through) so a Redis outage doesn't block the whole pipeline — this trades a few
        duplicates for availability, the right choice for an ingestion path.
        If not connected, check_and_store warns and returns False.
    ALTERNATIVE: in-memory set (lost on restart, no shared state across instances). Chosen Redis
        because it survives restarts and is shared across ingestion-service replicas.
    # GAP: dedup key is built in main.py (f"odds:{providerId}:{eventId}:{sequence}"), not here,
    #    so key construction logic is duplicated across process_odds/process_event/process_settlement.
    #    See 07_issues_found.md.
    # INTERVIEW: SET NX EX is the classic Redis idempotency pattern — atomic, so no race between
    #    check and set even under concurrent workers.
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86400,  # 24 hours default
        key_prefix: str = "dedup:",
    ):
        """Store connection config; the Redis client is created lazily on connect().

        WHAT: Assigns redis_url/ttl_seconds/key_prefix; initializes _client=None, _connected=False.
        WHY: Deferring connection to connect() lets the object be constructed in main.py before
            the event loop is ready and connected explicitly in lifespan().
        INPUTS: redis_url, ttl_seconds, key_prefix.
        OUTPUTS: None; sets attributes.
        SIDE EFFECTS: none (no I/O in constructor).
        FAILURE MODES: none.
        """
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self._client: Optional[Redis] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """True only after a successful connect() and while the client is live."""
        return self._connected and self._client is not None

    async def connect(self):
        """Connect to Redis and verify with PING.

        WHAT: Creates redis.from_url(...) client, awaits ping(), sets _connected=True.
        WHY: lifespan() calls this so the service verifies Redis is reachable before accepting
            traffic (fail-fast on startup).
        INPUTS: none (uses self.redis_url).
        OUTPUTS: None; sets self._client and self._connected.
        SIDE EFFECTS: opens a Redis connection.
        FAILURE MODES: Redis unreachable → logs error, sets _connected=False, re-raises so
            lifespan() aborts startup (fail-fast).
        """
        try:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info(f"Deduplicator connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            raise

    async def disconnect(self):
        """Close the Redis client.

        WHAT: Closes self._client, clears it, sets _connected=False.
        WHY: lifespan() calls this on shutdown to release the Redis connection cleanly.
        """
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False
        logger.info("Deduplicator disconnected")

    async def check_and_store(self, key: str) -> bool:
        """Atomically check if key exists and store it if not.

        WHAT: SET full_key "1" NX EX ttl_seconds. Returns True if key already existed (duplicate),
            False if newly stored.
        WHY: The core idempotency check — NX makes check-and-set atomic, so concurrent workers
            can't both process the same key.
        INPUTS: key (deduplication key, e.g. "odds:provider_0:evt_1:42").
        OUTPUTS: bool — True = duplicate (already existed → skip processing),
            False = new (stored → process it).
        SIDE EFFECTS: writes a key to Redis with a TTL.
        FAILURE MODES: Redis error → logged, returns False (allow-through, favor availability).
            Not connected → warns, returns False.
        ALTERNATIVE: Lua script or Redis transaction; SET NX EX is simpler and atomic by itself.
        # INTERVIEW: returning True for "duplicate" is intentionally counter-intuitive — read the
        #    docstring before using it; main.py skips forwarding when True.
        """
        if not self._client or not self._connected:
            logger.warning("Deduplicator not connected, allowing all")
            return False

        full_key = f"{self.key_prefix}{key}"

        try:
            # Use SET NX EX for atomic check-and-set with TTL
            result = await self._client.set(
                full_key,
                "1",
                nx=True,  # Only set if not exists
                ex=self.ttl_seconds,
            )

            # result is True if set (new), False if already exists (duplicate)
            return result is False

        except Exception as e:
            logger.error(f"Deduplication check failed for {key}: {e}")
            # On error, allow through to avoid blocking
            return False

    async def check_only(self, key: str) -> bool:
        """Check if key exists without storing (read-only)."""
        if not self._client or not self._connected:
            return False

        full_key = f"{self.key_prefix}{key}"

        try:
            exists = await self._client.exists(full_key)
            return exists > 0
        except Exception as e:
            logger.error(f"Deduplication check failed for {key}: {e}")
            return False

    async def remove(self, key: str) -> bool:
        """Remove a key from the deduplication store (e.g. for reprocessing)."""
        if not self._client or not self._connected:
            return False

        full_key = f"{self.key_prefix}{key}"

        try:
            result = await self._client.delete(full_key)
            return result > 0
        except Exception as e:
            logger.error(f"Deduplication remove failed for {key}: {e}")
            return False

    async def clear_prefix(self, prefix: str = "") -> int:
        """Clear all keys with the given prefix using SCAN."""
        if not self._client or not self._connected:
            return 0

        search_prefix = f"{self.key_prefix}{prefix}*"

        try:
            count = 0
            async for key in self._client.scan_iter(match=search_prefix):
                await self._client.delete(key)
                count += 1
            return count
        except Exception as e:
            logger.error(f"Deduplication clear failed: {e}")
            return 0

    async def get_ttl(self, key: str) -> int:
        """Get remaining TTL for a key (-1 if missing/not connected)."""
        if not self._client or not self._connected:
            return -1

        full_key = f"{self.key_prefix}{key}"

        try:
            ttl = await self._client.ttl(full_key)
            return ttl
        except Exception as e:
            logger.error(f"Deduplication TTL check failed for {key}: {e}")
            return -1


class SlidingWindowDeduplicator:
    """Advanced deduplicator using a Redis sorted set per entity for out-of-order handling.

    WHAT: Tracks sequence numbers per entity in a sorted set; rejects duplicates and sequences
        older than a configurable window (too_old), accepts new ones.
    WHY: Handles out-of-order deliveries where an older sequence legitimately arrives after a
        newer one — plain dedup would wrongly reject it as a duplicate.
    INPUTS (constructor): redis_url, window_size (1000), ttl_seconds (86400).
    GAP: Defined but NOT wired in main.py (dead code). See 07_issues_found.md.
    """

    def __init__(
        self,
        redis_url: str,
        window_size: int = 1000,
        ttl_seconds: int = 86400,
    ):
        self.redis_url = redis_url
        self.window_size = window_size
        self.ttl_seconds = ttl_seconds
        self._client: Optional[Redis] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self):
        try:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            self._connected = True
            logger.info(f"SlidingWindowDeduplicator connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            raise

    async def disconnect(self):
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False

    async def check_sequence(self, entity_key: str, sequence: int) -> tuple[bool, str]:
        """Validate a sequence: returns (is_valid, reason) — reason in {duplicate, too_old, accepted, not_connected, error_allowed}."""
        if not self._client or not self._connected:
            return True, "not_connected"

        key = f"seq:{entity_key}"

        try:
            existing = await self._client.zscore(key, str(sequence))
            if existing is not None:
                return False, "duplicate"

            max_seq = await self._client.zrevrange(key, 0, 0, withscores=True)
            if max_seq:
                max_sequence = int(max_seq[0][1])
                if sequence <= max_sequence - self.window_size:
                    return False, "too_old"

            await self._client.zadd(key, {str(sequence): sequence})
            await self._client.expire(key, self.ttl_seconds)

            # Cleanup old entries (keep window size)
            await self._client.zremrangebyscore(key, "-inf", max_sequence - self.window_size)

            return True, "accepted"

        except Exception as e:
            logger.error(f"Sequence check failed for {entity_key}:{sequence}: {e}")
            return True, "error_allowed"


class BloomFilterDeduplicator:
    """Probabilistic deduplicator (memory-efficient, allows false positives, no false negatives).

    WHAT: Would use a Redis-backed Bloom filter for high-volume streams where exact dedup
        uses too much memory. Currently falls back to a simple set-based check_and_add.
    WHY: For very high throughput, storing every key in Redis is expensive; a Bloom filter
        trades a small false-positive rate (dropping a rare legitimate update) for bounded memory.
    GAP: The RedisBloom module (BF.ADD/BF.EXISTS) is not actually used; falls back to set-based
        check_and_add. Dead-ish code path. See 07_issues_found.md.
    """

    def __init__(
        self,
        redis_url: str,
        capacity: int = 1_000_000,
        error_rate: float = 0.001,
        key_prefix: str = "bloom:",
    ):
        self.redis_url = redis_url
        self.capacity = capacity
        self.error_rate = error_rate
        self.key_prefix = key_prefix
        self._client: Optional[Redis] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self):
        try:
            self._client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            self._connected = True
            logger.info(f"BloomFilterDeduplicator connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._connected = False
            raise

    async def disconnect(self):
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False

    async def check_and_add(self, key: str) -> bool:
        """Return True if possibly duplicate, False if definitely new."""
        if not self._client or not self._connected:
            return False

        bloom_key = f"{self.key_prefix}filter"

        try:
            full_key = f"{self.key_prefix}{key}"
            result = await self._client.set(full_key, "1", nx=True, ex=86400)
            return result is False
        except Exception as e:
            logger.error(f"Bloom filter check failed for {key}: {e}")
            return False
