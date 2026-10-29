"""Concurrency and atomicity stress tests for Redis-backed rate limiters (Day 42).

Fires simultaneous concurrent requests via ThreadPoolExecutor against the same user key
to verify that Redis atomic operations (INCR) and Lua scripts prevent race conditions,
guaranteeing that EXACTLY the configured limit is admitted with zero over-admission.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

import fakeredis.aioredis as fake_aio
import pytest

from src.algorithms.async_redis_sliding_window_counter import (
    AsyncRedisSlidingWindowCounter,
)
from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket
from src.storage.redis_client import get_shared_fake_server


def _fire_concurrent_requests(
    limiter, user_id: str, count: int = 50
) -> tuple[int, int]:
    """Fires `count` simultaneous requests across threads against `limiter` for `user_id`."""
    allowed = 0
    blocked = 0

    with ThreadPoolExecutor(max_workers=min(32, count)) as executor:
        futures = [executor.submit(limiter.is_allowed, user_id) for _ in range(count)]
        for future in as_completed(futures):
            if future.result():
                allowed += 1
            else:
                blocked += 1

    return allowed, blocked


def test_concurrent_fixed_window_atomicity(redis_client):
    """Verifies RedisFixedWindow INCR atomic operation allows EXACTLY limit requests."""
    limit = 10
    limiter = RedisFixedWindow(redis_client, limit=limit, window_seconds=10)
    user = "user_concurrent_rfw"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_token_bucket_lua_atomicity(redis_client):
    """Verifies RedisTokenBucket Lua script atomicity admits EXACTLY capacity requests."""
    capacity = 10
    limiter = RedisTokenBucket(
        redis_client, capacity=capacity, refill_rate_per_sec=0.01
    )
    user = "user_concurrent_rtb"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == capacity, f"Expected exactly {capacity} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_leaky_bucket_lua_atomicity(redis_client):
    """Verifies RedisLeakyBucket Lua script atomicity admits EXACTLY capacity requests."""
    capacity = 10
    limiter = RedisLeakyBucket(redis_client, capacity=capacity, leak_rate_per_sec=0.01)
    user = "user_concurrent_rlb"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == capacity, f"Expected exactly {capacity} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_sliding_window_log_lua_atomicity(redis_client):
    """Verifies Lua-scripted RedisSlidingWindowLog admits EXACTLY limit requests."""
    limit = 10
    limiter = RedisSlidingWindowLog(redis_client, limit=limit, window_seconds=10)
    user = "user_concurrent_rswl"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


def test_concurrent_sliding_window_counter_lua_atomicity(redis_client):
    """Verifies RedisSlidingWindowCounter Lua script atomicity admits EXACTLY limit requests."""
    limit = 10
    limiter = RedisSlidingWindowCounter(redis_client, limit=limit, window_seconds=10)
    user = "user_concurrent_rswc"

    allowed, blocked = _fire_concurrent_requests(limiter, user, count=50)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert limiter.remaining(user) == 0


@pytest.mark.asyncio
async def test_concurrent_async_sliding_window_counter_atomicity():
    """Verifies AsyncRedisSlidingWindowCounter Lua script atomicity under 50 concurrent async tasks."""
    server = get_shared_fake_server()
    client = fake_aio.FakeRedis(server=server, db=2, decode_responses=True)
    await client.flushdb()

    limit = 10
    limiter = AsyncRedisSlidingWindowCounter(client, limit=limit, window_seconds=10)
    user = "user_concurrent_async_rswc"

    results = await asyncio.gather(*[limiter.is_allowed(user) for _ in range(50)])
    allowed = sum(1 for r in results if r is True)
    blocked = sum(1 for r in results if r is False)

    assert allowed == limit, f"Expected exactly {limit} allowed, got {allowed}"
    assert blocked == 40, f"Expected exactly 40 blocked, got {blocked}"
    assert await limiter.remaining(user) == 0
    await client.flushdb()


@pytest.mark.asyncio
async def test_sync_and_async_sliding_window_counter_share_state(redis_client):
    """Verifies sync and async Sliding Window Counter use identical key prefixes and share state."""
    server = get_shared_fake_server()
    async_client = fake_aio.FakeRedis(server=server, db=1, decode_responses=True)

    limit = 6
    user = "shared_swc_user"
    sync_limiter = RedisSlidingWindowCounter(redis_client, limit=limit, window_seconds=60)
    async_limiter = AsyncRedisSlidingWindowCounter(async_client, limit=limit, window_seconds=60)

    # 1. Sync limiter allows 3 requests
    for i in range(3):
        assert sync_limiter.is_allowed(user) is True

    # 2. Async limiter observes remaining quota = 3
    remaining = await async_limiter.remaining(user)
    assert remaining == 3, f"Expected async limiter to see remaining=3, got {remaining}"

    # 3. Async limiter consumes remaining 3 requests
    for i in range(3):
        assert await async_limiter.is_allowed(user) is True

    # 4. 7th request blocked on BOTH sync and async
    assert sync_limiter.is_allowed(user) is False
    assert await async_limiter.is_allowed(user) is False
    assert sync_limiter.remaining(user) == 0
    assert await async_limiter.remaining(user) == 0

