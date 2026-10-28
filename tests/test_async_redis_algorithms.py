"""Tests for Asynchronous Redis-backed rate limiting algorithms (Day 48).

Validates non-blocking async execution, Lua atomicity, and quota correctness
for all 5 rate limiting algorithms running over redis.asyncio.
"""

import asyncio

import fakeredis.aioredis as fake_aio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.algorithms.async_redis_fixed_window import AsyncRedisFixedWindow
from src.algorithms.async_redis_leaky_bucket import AsyncRedisLeakyBucket
from src.algorithms.async_redis_sliding_window_counter import (
    AsyncRedisSlidingWindowCounter,
)
from src.algorithms.async_redis_sliding_window_log import AsyncRedisSlidingWindowLog
from src.algorithms.async_redis_token_bucket import AsyncRedisTokenBucket
from src.middleware.config import EndpointRule
from src.middleware.rate_limit_middleware import RateLimitMiddleware


@pytest.fixture
def async_redis():
    """Provides an isolated async Redis client bound to DB 1."""
    client = fake_aio.FakeRedis(db=1, decode_responses=True)
    asyncio.run(client.flushdb())
    yield client
    asyncio.run(client.flushdb())


@pytest.mark.asyncio
async def test_async_token_bucket_basic(async_redis):
    limiter = AsyncRedisTokenBucket(async_redis, capacity=5, refill_rate_per_sec=1.0)
    user = "async_tb_user"

    # Should allow 5 requests
    for i in range(5):
        allowed = await limiter.is_allowed(user)
        assert allowed is True, f"Request {i+1} should have been allowed"

    # 6th should be rejected
    assert await limiter.is_allowed(user) is False
    assert await limiter.remaining(user) == 0


@pytest.mark.asyncio
async def test_async_sliding_window_log(async_redis):
    limiter = AsyncRedisSlidingWindowLog(async_redis, limit=3, window_seconds=10)
    user = "async_swl_user"

    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is False
    assert await limiter.remaining(user) == 0


@pytest.mark.asyncio
async def test_async_fixed_window(async_redis):
    limiter = AsyncRedisFixedWindow(async_redis, limit=4, window_seconds=10)
    user = "async_fw_user"

    for _ in range(4):
        assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is False
    assert await limiter.remaining(user) == 0


@pytest.mark.asyncio
async def test_async_sliding_window_counter(async_redis):
    limiter = AsyncRedisSlidingWindowCounter(async_redis, limit=3, window_seconds=10)
    user = "async_swc_user"

    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is False


@pytest.mark.asyncio
async def test_async_leaky_bucket(async_redis):
    limiter = AsyncRedisLeakyBucket(async_redis, capacity=3, leak_rate_per_sec=1.0)
    user = "async_lb_user"

    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is True
    assert await limiter.is_allowed(user) is False


@pytest.mark.asyncio
async def test_async_middleware_integration(async_redis):
    """Verifies RateLimitMiddleware with async Redis client under AsyncClient."""
    app = FastAPI(title="AsyncRateFortress")
    rules = {
        "default": EndpointRule(limit=3, window_seconds=60, algorithm="token_bucket"),
        "/api/async-test": EndpointRule(
            limit=3, window_seconds=60, algorithm="token_bucket"
        ),
    }
    app.add_middleware(RateLimitMiddleware, rules=rules, async_redis_client=async_redis)

    @app.get("/api/async-test")
    async def async_route():
        return {"status": "ok"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        headers = {"X-API-Key": "key_free_abc"}
        for i in range(3):
            r = await ac.get("/api/async-test", headers=headers)
            assert r.status_code == 200
            assert int(r.headers["X-RateLimit-Remaining"]) == 2 - i

        # 4th request must be throttled with 429
        r4 = await ac.get("/api/async-test", headers=headers)
        assert r4.status_code == 429
        assert r4.json()["error"] == "rate limit exceeded"
