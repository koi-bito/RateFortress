"""Shared pytest configuration and fixtures for RateFortress test suite.

Provides isolated Redis test database fixtures (DB index 1) that flush cleanly
before and after each test run, ensuring test isolation from development data (DB 0).
"""

import os

import pytest

from src.storage.redis_client import get_redis_client

# Ensure tests default to fast isolated execution unless live Redis is targeted
if not os.getenv("TARGET_LIVE_REDIS"):
    os.environ["USE_FAKE_REDIS"] = "true"



@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    """Ensures test runs default to fast isolated execution unless live Redis is targeted."""
    if not os.getenv("TARGET_LIVE_REDIS"):
        monkeypatch.setenv("USE_FAKE_REDIS", "true")


@pytest.fixture
def redis_client():
    """Provides a fresh, isolated Redis client bound to DB index 1.
    Flushes the test database before and after each test.
    """
    client = get_redis_client(db=1)
    client.flushdb()
    yield client
    client.flushdb()
