"""Deduplicator using Redis for idempotent processing."""
import logging
from typing import Optional
import redis.asyncio as redis
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class Deduplicator:
    """Redis-based deduplicator with TTL expiration."""

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 86400,  # 24 hours default
        key_prefix: str = "dedup:",
    ):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self._client: Optional[Redis] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self):
        """Connect to Redis."""
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
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            self._client = None
        self._connected = False
        logger.info("Deduplicator disconnected")

    async def check_and_store(self, key: str) -> bool:
        """
        Check if key exists and store if not.
        Returns True if duplicate (already exists), False if new.
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
        """Check if key exists without storing."""
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
        """Remove a key from deduplication store."""
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
        """Clear all keys with given prefix."""
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
        """Get remaining TTL for a key."""
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
    """
    Advanced deduplicator using sliding window for out-of-order handling.
    Stores sequence numbers per entity and handles gaps.
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
        """Connect to Redis."""
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
        """
        Check if sequence is valid (not duplicate, not too old).
        Returns (is_valid, reason).
        """
        if not self._client or not self._connected:
            return True, "not_connected"

        key = f"seq:{entity_key}"

        try:
            # Use Redis sorted set with sequence as score
            # This allows efficient range queries for window management

            # Check if already exists
            existing = await self._client.zscore(key, str(sequence))
            if existing is not None:
                return False, "duplicate"

            # Get current max sequence
            max_seq = await self._client.zrevrange(key, 0, 0, withscores=True)
            if max_seq:
                max_sequence = int(max_seq[0][1])
                # Check if sequence is too old (outside window)
                if sequence <= max_sequence - self.window_size:
                    return False, "too_old"

            # Add to sorted set
            await self._client.zadd(key, {str(sequence): sequence})
            # Set TTL on the key
            await self._client.expire(key, self.ttl_seconds)

            # Cleanup old entries (keep window size)
            await self._client.zremrangebyscore(key, "-inf", max_sequence - self.window_size)

            return True, "accepted"

        except Exception as e:
            logger.error(f"Sequence check failed for {entity_key}:{sequence}: {e}")
            return True, "error_allowed"


class BloomFilterDeduplicator:
    """
    Probabilistic deduplicator using Redis-backed Bloom filter.
    Memory efficient for high-volume streams with acceptable false positive rate.
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
        """
        Check if key might exist (Bloom filter) and add.
        Returns True if possibly duplicate, False if definitely new.
        Note: False positives possible but no false negatives.
        """
        if not self._client or not self._connected:
            return False

        bloom_key = f"{self.key_prefix}filter"

        try:
            # Use Redis BF module if available, otherwise fallback to simple set
            # For simplicity, using set-based approach here
            # In production, use RedisBloom module: BF.ADD / BF.EXISTS
            full_key = f"{self.key_prefix}{key}"
            result = await self._client.set(full_key, "1", nx=True, ex=86400)
            return result is False
        except Exception as e:
            logger.error(f"Bloom filter check failed for {key}: {e}")
            return False