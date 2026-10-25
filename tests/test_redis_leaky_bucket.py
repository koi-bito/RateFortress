"""Unit and integration tests for RedisLeakyBucket algorithm."""

import time

import pytest

from src.algorithms.redis_leaky_bucket import RedisLeakyBucket


def test_allows_up_to_capacity(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=3, leak_rate_per_sec=1.0)
    user = "user_lb_cap"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    # 4th request exceeds capacity
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0
    assert limiter.get_queue_size(user) == 3
    assert limiter.retry_after(user) >= 1


def test_leaks_over_time(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=2, leak_rate_per_sec=2.0)
    user = "user_lb_leak"

    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False

    # Sleep 1.1s -> at 2 req/s, both slots should leak out
    time.sleep(1.1)
    assert limiter.get_queue_size(user) == 0
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_no_extra_burst_after_idle(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=3, leak_rate_per_sec=1.0)
    user = "user_lb_idle"

    # Idle for 1 second before first request
    time.sleep(1.0)

    # Cannot burst past capacity of 3
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_independent_per_user(redis_client):
    limiter = RedisLeakyBucket(redis_client, capacity=2, leak_rate_per_sec=0.1)
    u1, u2 = "u1", "u2"

    assert limiter.is_allowed(u1) is True
    assert limiter.is_allowed(u1) is True
    assert limiter.is_allowed(u1) is False

    assert limiter.is_allowed(u2) is True
    assert limiter.is_allowed(u2) is True
    assert limiter.is_allowed(u2) is False


def test_multi_instance_shared_state(redis_client):
    inst1 = RedisLeakyBucket(redis_client, capacity=4, leak_rate_per_sec=0.1)
    inst2 = RedisLeakyBucket(redis_client, capacity=4, leak_rate_per_sec=0.1)
    shared_user = "shared_lb_user"

    assert inst1.is_allowed(shared_user) is True
    assert inst2.is_allowed(shared_user) is True
    assert inst1.is_allowed(shared_user) is True
    assert inst2.is_allowed(shared_user) is True

    # 5th request blocked on both instances
    assert inst1.is_allowed(shared_user) is False
    assert inst2.is_allowed(shared_user) is False


def test_invalid_inputs(redis_client):
    with pytest.raises(ValueError):
        RedisLeakyBucket(redis_client, capacity=0, leak_rate_per_sec=1.0)

    with pytest.raises(ValueError):
        RedisLeakyBucket(redis_client, capacity=5, leak_rate_per_sec=-1.0)
