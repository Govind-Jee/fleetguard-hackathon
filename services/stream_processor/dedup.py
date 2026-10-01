"""
FleetGuard Pulse - Stream Deduplication Engine

Provides two-tier duplicate detection:
1. Counting Bloom Filter for O(1) probabilistic set membership with support for decrements/eviction.
2. Exact secondary verification store (Bounded LRU / Redis) to completely eliminate false-positive drops.
"""

import collections
import hashlib
import logging
from typing import List, Optional
from services.stream_processor.metrics import default_metrics

logger = logging.getLogger("stream_processor.dedup")


class CountingBloomFilter:
    """
    Counting Bloom Filter implementation with configurable size and hash functions.
    Supports add, contains, and remove operations for sliding-window deduplication.
    """

    def __init__(self, capacity: int = 100000, error_rate: float = 0.001):
        """
        Initialize Counting Bloom Filter with theoretical optimal bit array size and hash count.
        """
        import math

        self.capacity = capacity
        self.error_rate = error_rate

        # Optimal size m = - (n * ln(p)) / (ln(2)^2)
        self.size = max(1024, int(-1 * (capacity * math.log(error_rate)) / (math.log(2) ** 2)))
        # Optimal hash count k = (m / n) * ln(2)
        self.num_hashes = max(3, int((self.size / capacity) * math.log(2)))

        # Counters array: 8-bit counters (0 to 255)
        self.counters = [0] * self.size
        self._count = 0

    def _hashes(self, item: str) -> List[int]:
        """
        Generate k hash indices for a given item using Kirsch-Mitzenmacher double hashing:
        g_i(x) = (h1(x) + i * h2(x)) mod m.
        Uses a single 16-byte BLAKE2b digest providing two 64-bit independent hashes.
        """
        raw_bytes = item.encode("utf-8")
        digest = hashlib.blake2b(raw_bytes, digest_size=16).digest()
        h1 = int.from_bytes(digest[:8], byteorder="big")
        h2 = int.from_bytes(digest[8:], byteorder="big") | 1  # ensure odd/non-zero
        size = self.size
        return [(h1 + i * h2) % size for i in range(self.num_hashes)]

    def add(self, item: str) -> None:
        """Add an item to the filter, incrementing counters."""
        for idx in self._hashes(item):
            if self.counters[idx] < 255:  # Prevent 8-bit overflow
                self.counters[idx] += 1
        self._count += 1

    def contains(self, item: str) -> bool:
        """Check if an item is possibly in the filter. False means definitely not present."""
        for idx in self._hashes(item):
            if self.counters[idx] == 0:
                return False
        return True

    def remove(self, item: str) -> bool:
        """Remove an item from the filter if present, decrementing counters."""
        if not self.contains(item):
            return False
        for idx in self._hashes(item):
            if self.counters[idx] > 0:
                self.counters[idx] -= 1
        self._count = max(0, self._count - 1)
        return True

    @property
    def approximate_items(self) -> int:
        return self._count


class TwoTierDeduplicator:
    """
    Two-Tier Idempotent Deduplicator:
    Tier 1: Fast In-Memory Counting Bloom Filter.
    Tier 2: Exact verification store (Bounded LRU cache or Redis cache) to prevent false positives.
    """

    def __init__(
        self,
        capacity: int = 200000,
        exact_cache_size: int = 100000,
        redis_client=None,
        metrics=None,
    ):
        self.bloom_filter = CountingBloomFilter(capacity=capacity, error_rate=0.001)
        self.exact_cache_size = exact_cache_size
        self.exact_cache = collections.OrderedDict()
        self.redis_client = redis_client
        self.metrics = metrics or default_metrics

    def is_duplicate(self, event_id: str) -> bool:
        """
        Determines whether event_id has already been processed.

        Returns:
            True if event is a confirmed duplicate.
            False if event is new (and records it for future checks).
        """
        # Step 1: Check Counting Bloom Filter
        might_exist = self.bloom_filter.contains(event_id)

        if not might_exist:
            # Definitely not seen before!
            self.bloom_filter.add(event_id)
            self._record_exact(event_id)
            return False

        # Step 2: Bloom Filter says 'might exist' -> Check Tier 2 exact store
        is_exact_dup = self._check_exact(event_id)

        if is_exact_dup:
            self.metrics.increment("events_duplicate")
            logger.debug("Suppressed duplicate event_id: %s", event_id)
            return True
        else:
            # False positive in Bloom Filter! Record in exact store.
            self.bloom_filter.add(event_id)
            self._record_exact(event_id)
            return False

    def _record_exact(self, event_id: str) -> None:
        """Record event_id in exact store (LRU and optionally Redis)."""
        # Memory LRU
        self.exact_cache[event_id] = True
        if len(self.exact_cache) > self.exact_cache_size:
            evicted, _ = self.exact_cache.popitem(last=False)
            # Evict from counting bloom filter to prevent saturation
            self.bloom_filter.remove(evicted)

        # Optional Redis persistence with 24-hour TTL
        if self.redis_client:
            try:
                self.redis_client.set(f"event:dedup:{event_id}", "1", ex=86400)
            except Exception as e:
                logger.warning("Redis dedup set error: %s", e)

    def _check_exact(self, event_id: str) -> bool:
        """Check exact membership."""
        if event_id in self.exact_cache:
            # Move to end (most recently used)
            self.exact_cache.move_to_end(event_id)
            return True

        if self.redis_client:
            try:
                exists = self.redis_client.exists(f"event:dedup:{event_id}")
                return bool(exists)
            except Exception as e:
                logger.warning("Redis dedup exists check error: %s", e)

        return False
