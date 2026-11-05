"""Circuit Breaker pattern for RateFortress resilience."""

import time
from collections.abc import Callable
from typing import Any


class CircuitBreaker:
    """Stateful circuit breaker with Closed, Open, and Half-Open states."""

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fail_open: bool = True,
    ):
        if failure_threshold <= 0:
            raise ValueError("Failure threshold must be positive.")
        if recovery_timeout <= 0:
            raise ValueError("Recovery timeout must be positive.")

        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.fail_open = fail_open

        self.failures = 0
        self.state = self.STATE_CLOSED
        self.opened_at: float | None = None

    def call(self, func: Callable, *args, fallback: Any | None = None, **kwargs) -> Any:
        effective_fallback = self.fail_open if fallback is None else fallback
        now = time.time()

        # Check if open circuit has reached recovery timeout
        if self.state == self.STATE_OPEN:
            if self.opened_at is not None and (
                now - self.opened_at > self.recovery_timeout
            ):
                self.state = self.STATE_HALF_OPEN
            else:
                return effective_fallback

        try:
            result = func(*args, **kwargs)

            # Success in half-open state confirms recovery -> reset to closed
            if self.state == self.STATE_HALF_OPEN:
                self.state = self.STATE_CLOSED
                self.failures = 0
                self.opened_at = None
            elif self.state == self.STATE_CLOSED:
                self.failures = 0

            return result
        except Exception:
            self.failures += 1
            if (
                self.failures >= self.failure_threshold
                or self.state == self.STATE_HALF_OPEN
            ):
                self.state = self.STATE_OPEN
                self.opened_at = time.time()

            return effective_fallback

    async def async_call(
        self, func: Callable, *args, fallback: Any | None = None, **kwargs
    ) -> Any:
        effective_fallback = self.fail_open if fallback is None else fallback
        now = time.time()

        # Check if open circuit has reached recovery timeout
        if self.state == self.STATE_OPEN:
            if self.opened_at is not None and (
                now - self.opened_at > self.recovery_timeout
            ):
                self.state = self.STATE_HALF_OPEN
            else:
                return effective_fallback

        try:
            result = await func(*args, **kwargs)

            # Success in half-open state confirms recovery -> reset to closed
            if self.state == self.STATE_HALF_OPEN:
                self.state = self.STATE_CLOSED
                self.failures = 0
                self.opened_at = None
            elif self.state == self.STATE_CLOSED:
                self.failures = 0

            return result
        except Exception:
            self.failures += 1
            if (
                self.failures >= self.failure_threshold
                or self.state == self.STATE_HALF_OPEN
            ):
                self.state = self.STATE_OPEN
                self.opened_at = time.time()

            return effective_fallback

    def reset(self) -> None:
        self.state = self.STATE_CLOSED
        self.failures = 0
        self.opened_at = None

    @property
    def is_closed(self) -> bool:
        return self.state == self.STATE_CLOSED

    @property
    def is_open(self) -> bool:
        return self.state == self.STATE_OPEN

    @property
    def is_half_open(self) -> bool:
        return self.state == self.STATE_HALF_OPEN
