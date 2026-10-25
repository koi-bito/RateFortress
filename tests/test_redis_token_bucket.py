"""Unit and integration tests for RedisTokenBucket algorithm."""

import time

import pytest

from src.algorithms.redis_token_bucket import RedisTokenBucket


def test_burst_up_to_capacity(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=5, refill_rate_per_sec=1.0)
    user = "user_burst"

    for _ in range(5):
        assert limiter.is_allowed(user) is True

    # 6th request should be blocked
    assert limiter.is_allowed(user) is False
    assert limiter.remaining(user) == 0
    assert limiter.retry_after(user) >= 1


def test_refill_over_time(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=3, refill_rate_per_sec=2.0)
    user = "user_refill"

    # Exhaust bucket
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False

    # Sleep for 1.1s -> should refill at least 2 tokens
    time.sleep(1.1)
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_capacity_cap_after_idle(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=4, refill_rate_per_sec=10.0)
    user = "user_cap"

    # Wait to ensure refill doesn't exceed capacity
    time.sleep(0.5)
    assert limiter.remaining(user) == 4

    for _ in range(4):
        assert limiter.is_allowed(user) is True
    assert limiter.is_allowed(user) is False


def test_multi_token_consumption(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=10, refill_rate_per_sec=1.0)
    user = "user_batch"

    assert limiter.is_allowed(user, tokens=4) is True
    assert limiter.remaining(user) == 6
    assert limiter.is_allowed(user, tokens=6) is True
    assert limiter.remaining(user) == 0
    assert limiter.is_allowed(user, tokens=1) is False


def test_independent_per_user(redis_client):
    limiter = RedisTokenBucket(redis_client, capacity=2, refill_rate_per_sec=0.1)
    u1, u2 = "u1", "u2"

    assert limiter.is_allowed(u1) is True
    assert limiter.is_allowed(u1) is True
    assert limiter.is_allowed(u1) is False

    # u2 should have independent quota
    assert limiter.is_allowed(u2) is True
    assert limiter.is_allowed(u2) is True
    assert limiter.is_allowed(u2) is False


def test_multi_instance_shared_state(redis_client):
    inst1 = RedisTokenBucket(redis_client, capacity=4, refill_rate_per_sec=0.1)
    inst2 = RedisTokenBucket(redis_client, capacity=4, refill_rate_per_sec=0.1)
    shared_user = "shared_tb_user"

    # Alternating calls between 2 distinct app instance objects
    assert inst1.is_allowed(shared_user) is True
    assert inst2.is_allowed(shared_user) is True
    assert inst1.is_allowed(shared_user) is True
    assert inst2.is_allowed(shared_user) is True

    # 5th request blocked on both instances
    assert inst1.is_allowed(shared_user) is False
    assert inst2.is_allowed(shared_user) is False


def test_invalid_inputs(redis_client):
    with pytest.raises(ValueError):
        RedisTokenBucket(redis_client, capacity=0, refill_rate_per_sec=1.0)

    with pytest.raises(ValueError):
        RedisTokenBucket(redis_client, capacity=5, refill_rate_per_sec=-1.0)

    limiter = RedisTokenBucket(redis_client, capacity=5, refill_rate_per_sec=1.0)
    with pytest.raises(ValueError):
        limiter.is_allowed("u", tokens=0)
    with pytest.raises(ValueError):
        limiter.is_allowed("u", tokens=-2)
