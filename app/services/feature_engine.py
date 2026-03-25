"""
Redis-backed feature extraction for the streaming pipeline.
Uses sorted sets with timestamp scores for sliding-window counters.
Produces a numeric feature vector ready for the ML scorer.

Early attempts: Tried storing all events in PostgreSQL and querying by timestamp.
Problem: For 100 events/sec, querying 60-second windows became a bottleneck.

Solution: Redis sorted sets
  - ZADD/ZRANGEBYSCORE gives us O(log N) window queries
  - ZREMRANGEBYSCORE prunes stale entries cheaply  
  - No database I/O latency — entire operation is in-memory
  - Learned from: https://redis.io/docs/data-types/sorted-sets/
"""

import time
import logging
from typing import Optional

import numpy as np
import redis.asyncio as aioredis

logger = logging.getLogger("soc.features")

# feature window sizes in seconds
WINDOW_1M = 60
WINDOW_5M = 300
WINDOW_15M = 900

# the features we extract, in a fixed order for the ML model
FEATURE_NAMES = [
    "ip_req_count_1m",
    "ip_req_count_5m",
    "ip_fail_count_1m",
    "ip_fail_count_5m",
    "unique_paths_1m",
    "avg_status_code_1m",
    "is_post",
    "is_auth_endpoint",
    "status_is_401",
    "status_is_403",
    "status_is_500",
    "burst_rate",
]


class FeatureEngine:
    """Extracts streaming features from parsed log events."""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def extract(self, event: dict) -> np.ndarray:
        """
        Update Redis counters and return the feature vector for this event.
        This is called once per event in the streaming pipeline.
        """
        ip = event.get("source_ip", "unknown")
        now = time.time()
        path = event.get("path", "/")
        status = event.get("status_code") or 0
        method = event.get("method", "GET").upper()

        # update sorted sets — score is the unix timestamp
        pipe = self.redis.pipeline()

        # IP request counter
        req_key = f"feat:req:{ip}"
        pipe.zadd(req_key, {f"{now}": now})
        pipe.expire(req_key, WINDOW_15M + 60)  # ttl slightly beyond the largest window

        # IP failure counter (4xx/5xx)
        if status >= 400:
            fail_key = f"feat:fail:{ip}"
            pipe.zadd(fail_key, {f"{now}": now})
            pipe.expire(fail_key, WINDOW_15M + 60)

        # unique paths set
        path_key = f"feat:paths:{ip}"
        pipe.zadd(path_key, {path: now})
        pipe.expire(path_key, WINDOW_5M + 60)

        # status code accumulator for average
        status_key = f"feat:status:{ip}"
        pipe.zadd(status_key, {f"{status}:{now}": now})
        pipe.expire(status_key, WINDOW_5M + 60)

        await pipe.execute()

        # now read the window counts
        cutoff_1m = now - WINDOW_1M
        cutoff_5m = now - WINDOW_5M

        req_count_1m = await self.redis.zcount(req_key, cutoff_1m, now)
        req_count_5m = await self.redis.zcount(req_key, cutoff_5m, now)

        fail_key = f"feat:fail:{ip}"
        fail_count_1m = await self.redis.zcount(fail_key, cutoff_1m, now)
        fail_count_5m = await self.redis.zcount(fail_key, cutoff_5m, now)

        unique_paths_1m = await self.redis.zcount(path_key, cutoff_1m, now)

        # average status code in the last minute
        recent_statuses = await self.redis.zrangebyscore(status_key, cutoff_1m, now)
        avg_status = 0.0
        if recent_statuses:
            codes = []
            for entry in recent_statuses:
                try:
                    codes.append(int(entry.split(":")[0]))
                except (ValueError, IndexError):
                    pass
            avg_status = sum(codes) / len(codes) if codes else 0.0

        # burst rate: requests in the last 5 seconds
        burst_window = now - 5
        burst_count = await self.redis.zcount(req_key, burst_window, now)
        burst_rate = burst_count / 5.0

        # binary features
        is_post = 1.0 if method == "POST" else 0.0
        is_auth = 1.0 if "/auth" in path or "/login" in path or "/ssh" in path else 0.0
        is_401 = 1.0 if status == 401 else 0.0
        is_403 = 1.0 if status == 403 else 0.0
        is_500 = 1.0 if status == 500 else 0.0

        features = np.array([
            req_count_1m,
            req_count_5m,
            fail_count_1m,
            fail_count_5m,
            unique_paths_1m,
            avg_status,
            is_post,
            is_auth,
            is_401,
            is_403,
            is_500,
            burst_rate,
        ], dtype=np.float32)

        return features

    async def cleanup_stale(self, ip: str):
        """Remove all feature keys for an IP — called on IP block or periodic cleanup."""
        keys = [
            f"feat:req:{ip}", f"feat:fail:{ip}",
            f"feat:paths:{ip}", f"feat:status:{ip}",
        ]
        await self.redis.delete(*keys)
