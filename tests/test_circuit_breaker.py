"""Tests for CircuitBreaker resilience pattern."""

from unittest.mock import patch

from src.middleware.circuit_breaker import CircuitBreaker


def test_closed_state_success():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
    assert cb.is_closed

    result = cb.call(lambda: "success")
    assert result == "success"
    assert cb.is_closed
    assert cb.failures == 0


def test_trips_to_open_after_failure_threshold():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0, fail_open=True)

    call_count = 0

    def failing_call():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Redis unreachable")

    # Call 1 & 2 fail but don't trip breaker
    assert cb.call(failing_call) is True
    assert cb.failures == 1
    assert cb.is_closed
    assert call_count == 1

    assert cb.call(failing_call) is True
    assert cb.failures == 2
    assert cb.is_closed
    assert call_count == 2

    # Call 3 fails -> trips to OPEN
    assert cb.call(failing_call) is True
    assert cb.is_open
    assert call_count == 3

    # Next call fails fast without invoking the function
    assert cb.call(failing_call) is True
    assert cb.is_open
    assert call_count == 3  # func was NOT called


def test_half_open_recovery_cycle():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=5.0, fail_open=True)

    def failing_call():
        raise TimeoutError("Storage timeout")

    with patch("time.time", return_value=100.0):
        cb.call(failing_call)
        cb.call(failing_call)
        assert cb.is_open

    # 4 seconds later: still within recovery timeout -> remains OPEN
    with patch("time.time", return_value=104.0):
        assert cb.call(failing_call) is True
        assert cb.is_open

    # 6 seconds later (> recovery_timeout): transitions to HALF_OPEN
    # If the probe succeeds, circuit resets to CLOSED
    with patch("time.time", return_value=106.0):
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.is_closed
        assert cb.failures == 0


def test_failed_probe_in_half_open_reopens_immediately():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=5.0)

    def failing_call():
        raise TimeoutError("Still failing")

    with patch("time.time", return_value=100.0):
        cb.call(failing_call)
        cb.call(failing_call)
        assert cb.is_open

    # At t=106, probes half open and fails again -> trips directly to OPEN
    with patch("time.time", return_value=106.0):
        cb.call(failing_call)
        assert cb.is_open


def test_interleaved_failures_and_successes_reset_count_while_closed():
    """Verifies that successes in STATE_CLOSED reset failure count, preventing sporadic errors from tripping the breaker."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0, fail_open=True)

    def failing_call():
        raise ConnectionError("Intermittent network glitch")

    def successful_call():
        return "ok"

    # Simulate 20 iterations where 2 failures occur, followed by a success.
    # Total failures = 40, but never 3 consecutive failures.
    for i in range(20):
        # 1st failure -> failures = 1
        assert cb.call(failing_call) is True
        assert cb.failures == 1
        assert cb.is_closed

        # 2nd failure -> failures = 2
        assert cb.call(failing_call) is True
        assert cb.failures == 2
        assert cb.is_closed

        # Success -> failures MUST reset to 0
        assert cb.call(successful_call) == "ok"
        assert cb.failures == 0, f"Expected failures to reset to 0 on success at iteration {i}, got {cb.failures}"
        assert cb.is_closed

    # Circuit breaker remained CLOSED across all 60 calls despite 40 total failures!
    assert cb.is_closed
    assert cb.failures == 0


import pytest


@pytest.mark.asyncio
async def test_async_interleaved_failures_and_successes_reset_count():
    """Async variant: proves successes in STATE_CLOSED reset failures on async_call."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0, fail_open=True)

    async def async_failing():
        raise ConnectionError("Async glitch")

    async def async_success():
        return "async_ok"

    for _ in range(10):
        await cb.async_call(async_failing)
        assert cb.failures == 1
        await cb.async_call(async_failing)
        assert cb.failures == 2
        res = await cb.async_call(async_success)
        assert res == "async_ok"
        assert cb.failures == 0
        assert cb.is_closed

    assert cb.is_closed

