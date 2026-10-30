"""Unit and integration tests for RedisGCRA and AsyncRedisGCRA algorithms."""

import concurrent.futures
import time

import fakeredis.aioredis as fake_aio
import pytest

from src.algorithms.async_redis_gcra import AsyncRedisGCRA
from src.algorithms.redis_gcra import RedisGCRA


def test_redis_gcra_burst_and_recovery(redis_client):
    """Validates RedisGCRA allows bursts up to limit and recovers as time advances."""
    limiter = RedisGCRA(redis_client, limit=5, period=5.0)
    user = "redis_gcra_user"

    for _ in range(5):
        assert limiter.is_allowed(user) is True

    # 6th request should be blocked
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0
    assert limiter.retry_after(user) >= 1

    # Sleep 1.1s (1 emission interval) -> recovers at least 1 cell
    time.sleep(1.1)
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_redis_gcra_multi_instance_shared_state(redis_client):
    """Validates that multiple limiter instances share state via Redis keys."""
    instance_a = RedisGCRA(redis_client, limit=4, period=10.0, namespace="cluster")
    instance_b = RedisGCRA(redis_client, limit=4, period=10.0, namespace="cluster")
    user = "shared_gcra_user"

    # Instance A consumes 2
    assert instance_a.is_allowed(user) is True
    assert instance_a.is_allowed(user) is True

    # Instance B should observe remaining = 2
    assert instance_b.remaining(user) == 2

    # Instance B consumes 2
    assert instance_b.is_allowed(user) is True
    assert instance_b.is_allowed(user) is True

    # Both instances now block the 5th request
    assert instance_a.is_allowed(user) is False
    assert instance_b.is_allowed(user) is False


def test_redis_gcra_key_has_ttl(redis_client):
    """Validates that GCRA keys always have an explicit TTL set in Redis."""
    limiter = RedisGCRA(redis_client, limit=5, period=10.0)
    user = "ttl_gcra_user"
    limiter.is_allowed(user)

    key = limiter._key(user)
    ttl = redis_client.ttl(key)
    assert ttl > 0, f"Expected key {key} to have an explicit positive TTL, got {ttl}"


def test_redis_gcra_concurrent_atomicity(redis_client):
    """Validates that concurrent threads hammering GCRA strictly respect the limit (zero race conditions)."""
    limiter = RedisGCRA(redis_client, limit=10, period=60.0)
    user = "concurrent_gcra_user"

    results = []
    num_threads = 30

    def attempt_request():
        return limiter.is_allowed(user)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(attempt_request) for _ in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    allowed_count = sum(1 for r in results if r is True)
    blocked_count = sum(1 for r in results if r is False)

    assert allowed_count == 10, f"Expected exactly 10 allowed requests, got {allowed_count}"
    assert blocked_count == 20, f"Expected exactly 20 blocked requests, got {blocked_count}"


@pytest.mark.asyncio
async def test_async_redis_gcra_basic():
    """Validates AsyncRedisGCRA over redis.asyncio."""
    client = fake_aio.FakeRedis(db=1, decode_responses=True)
    await client.flushdb()
    try:
        limiter = AsyncRedisGCRA(client, limit=4, period=8.0)
        user = "async_gcra_user"

        for _ in range(4):
            assert await limiter.is_allowed(user) is True

        assert await limiter.is_allowed(user) is False
        assert await limiter.remaining(user) == 0
        assert await limiter.retry_after(user) >= 1
    finally:
        await client.flushdb()
