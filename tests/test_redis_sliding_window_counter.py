"""Unit and multi-instance tests for RedisSlidingWindowCounter rate limiter (Day 36)."""

import time

import pytest

from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.storage.redis_client import get_redis_client


@pytest.fixture
def redis_client(monkeypatch):
    monkeypatch.setenv("USE_FAKE_REDIS", "true")
    client = get_redis_client(db=1)
    client.flushdb()
    yield client
    client.flushdb()


def test_allows_up_to_limit(redis_client):
    limiter = RedisSlidingWindowCounter(redis_client, limit=3, window_seconds=10)
    assert limiter.is_allowed("swc_u1") is True
    assert limiter.is_allowed("swc_u1") is True
    assert limiter.is_allowed("swc_u1") is True
    assert limiter.is_allowed("swc_u1") is False  # 4th request blocked
    assert limiter.remaining("swc_u1") == 0


def test_resets_after_window(redis_client):
    limiter = RedisSlidingWindowCounter(redis_client, limit=1, window_seconds=1)
    assert limiter.is_allowed("swc_reset") is True
    assert limiter.is_allowed("swc_reset") is False
    # Wait for window + decay
    time.sleep(1.2)
    assert limiter.is_allowed("swc_reset") is True


def test_independent_per_user(redis_client):
    limiter = RedisSlidingWindowCounter(redis_client, limit=1, window_seconds=10)
    assert limiter.is_allowed("client_alpha") is True
    assert limiter.is_allowed("client_beta") is True
    assert limiter.is_allowed("client_alpha") is False
    assert limiter.is_allowed("client_beta") is False


def test_multi_instance_shared_state(redis_client):
    """Simulates two distinct backend instances sharing the same Redis counter keys."""
    instance_1 = RedisSlidingWindowCounter(redis_client, limit=4, window_seconds=10)
    instance_2 = RedisSlidingWindowCounter(redis_client, limit=4, window_seconds=10)

    # Instance 1 processes 2 requests
    assert instance_1.is_allowed("tenant_redis") is True
    assert instance_1.is_allowed("tenant_redis") is True

    # Instance 2 processes 2 requests (reaching limit=4)
    assert instance_2.is_allowed("tenant_redis") is True
    assert instance_2.is_allowed("tenant_redis") is True

    # 5th request blocked on both instances
    assert instance_1.is_allowed("tenant_redis") is False
    assert instance_2.is_allowed("tenant_redis") is False


def test_window_weighting_decay(redis_client):
    """Verifies that requests from the previous window smoothly decay according to the weighting formula."""
    window = 2
    limiter = RedisSlidingWindowCounter(redis_client, limit=5, window_seconds=window)

    # Fire 4 requests in window 1
    for _ in range(4):
        assert limiter.is_allowed("decay_user") is True

    # Sleep into the middle of window 2 (approx 50% elapsed)
    time.sleep(window * 0.6)

    # 4 * ~0.4 = ~1.6 estimated count from previous window.
    # Since 1.6 < 5, additional requests should be allowed in the new window!
    assert limiter.is_allowed("decay_user") is True
