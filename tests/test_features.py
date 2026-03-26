"""Tests for the feature engine."""

import numpy as np
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.services.feature_engine import FeatureEngine, FEATURE_NAMES


@pytest.fixture
def mock_redis(monkeypatch):
    """Use a mock-redis dict-based implementation for testing without a live Redis instance."""
    import asyncio

    class MockRedis:
        def __init__(self):
            self._data = {}

        def pipeline(self):
            return MockPipeline(self)

        async def zcount(self, key, min_score, max_score):
            if key not in self._data:
                return 0
            return sum(1 for _, s in self._data[key] if min_score <= s <= max_score)

        async def zrangebyscore(self, key, min_score, max_score):
            if key not in self._data:
                return []
            return [v for v, s in self._data[key] if min_score <= s <= max_score]

        async def delete(self, *keys):
            for k in keys:
                self._data.pop(k, None)

    class MockPipeline:
        def __init__(self, redis):
            self._redis = redis
            self._ops = []

        def zadd(self, key, mapping):
            for member, score in mapping.items():
                if key not in self._redis._data:
                    self._redis._data[key] = []
                self._redis._data[key].append((member, score))
            return self

        def expire(self, key, ttl):
            return self

        async def execute(self):
            return []

    return MockRedis()


@pytest.mark.asyncio
async def test_extract_returns_correct_shape(mock_redis):
    engine = FeatureEngine(mock_redis)
    event = {
        "source_ip": "192.168.1.10",
        "path": "/api/users",
        "status_code": 200,
        "method": "GET",
    }
    features = await engine.extract(event)
    assert isinstance(features, np.ndarray)
    assert features.shape == (len(FEATURE_NAMES),)
    assert features.dtype == np.float32


@pytest.mark.asyncio
async def test_post_to_auth_sets_binary_flags(mock_redis):
    engine = FeatureEngine(mock_redis)
    event = {
        "source_ip": "10.0.0.99",
        "path": "/api/auth/login",
        "status_code": 401,
        "method": "POST",
    }
    features = await engine.extract(event)
    # is_post (index 6) should be 1
    assert features[6] == 1.0
    # is_auth (index 7) should be 1
    assert features[7] == 1.0
    # is_401 (index 8) should be 1
    assert features[8] == 1.0


@pytest.mark.asyncio
async def test_cleanup_deletes_keys(mock_redis):
    engine = FeatureEngine(mock_redis)
    event = {
        "source_ip": "10.0.0.99",
        "path": "/test",
        "status_code": 200,
        "method": "GET",
    }
    await engine.extract(event)
    await engine.cleanup_stale("10.0.0.99")
    # all feature keys for this IP should be gone
    for prefix in ["feat:req:", "feat:fail:", "feat:paths:", "feat:status:"]:
        assert prefix + "10.0.0.99" not in mock_redis._data
