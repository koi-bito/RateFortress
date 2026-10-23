"""Unit and multi-instance tests for RedisFixedWindow rate limiter (Day 35)."""

import time

import pytest

from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.storage.redis_client import get_redis_client


@pytest.fixture
def redis_client(monkeypatch):
    monkeypatch.setenv("USE_FAKE_REDIS", "true")
    client = get_redis_client(db=1)
    client.flushdb()
    yield client
    client.flushdb()


def test_allows_up_to_limit(redis_client):
    limiter = RedisFixedWindow(redis_client, limit=3, window_seconds=10)
    assert limiter.is_allowed("user_1") is True
    assert limiter.is_allowed("user_1") is True
    assert limiter.is_allowed("user_1") is True
    assert limiter.is_allowed("user_1") is False  # 4th request blocked
    assert limiter.remaining("user_1") == 0


def test_resets_after_window(redis_client):
    limiter = RedisFixedWindow(redis_client, limit=1, window_seconds=1)
    assert limiter.is_allowed("user_reset") is True
    assert limiter.is_allowed("user_reset") is False
    time.sleep(1.1)
    assert limiter.is_allowed("user_reset") is True


def test_independent_per_user(redis_client):
    limiter = RedisFixedWindow(redis_client, limit=1, window_seconds=10)
    assert limiter.is_allowed("user_a") is True
    assert limiter.is_allowed("user_b") is True
    assert limiter.is_allowed("user_a") is False
    assert limiter.is_allowed("user_b") is False


def test_multi_instance_shared_state(redis_client):
    """Simulates two distinct application servers (App Server A and App Server B)
    sharing the same distributed Redis cluster.
    """
    server_a = RedisFixedWindow(redis_client, limit=4, window_seconds=10)
    server_b = RedisFixedWindow(redis_client, limit=4, window_seconds=10)

    # Server A handles 2 requests
    assert server_a.is_allowed("tenant_shared") is True
    assert server_a.is_allowed("tenant_shared") is True

    # Server B handles 2 requests (reaching the limit of 4)
    assert server_b.is_allowed("tenant_shared") is True
    assert server_b.is_allowed("tenant_shared") is True

    # 5th request: Server A tries to handle it -> Blocked!
    assert server_a.is_allowed("tenant_shared") is False

    # 6th request: Server B tries to handle it -> Blocked!
    assert server_b.is_allowed("tenant_shared") is False

    # Verify both servers report remaining = 0
    assert server_a.remaining("tenant_shared") == 0
    assert server_b.remaining("tenant_shared") == 0
