"""FastAPI / Starlette Rate Limiting Middleware for RateFortress.

Inspects incoming HTTP requests, resolves client identity (via API Key or IP),
matches hierarchical endpoint rules using an EndpointTrie, enforces rate quotas,
protects against backend crashes via CircuitBreaker fail-open resilience,
and attaches standard rate limit headers (X-RateLimit-Limit, Remaining, Retry-After).

Supports both synchronous and non-blocking asynchronous Redis algorithms,
preventing event loop thread blocking under high concurrent loads.
"""

import inspect
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.algorithms.async_redis_fixed_window import AsyncRedisFixedWindow
from src.algorithms.async_redis_leaky_bucket import AsyncRedisLeakyBucket
from src.algorithms.async_redis_sliding_window_counter import (
    AsyncRedisSlidingWindowCounter,
)
from src.algorithms.async_redis_sliding_window_log import AsyncRedisSlidingWindowLog
from src.algorithms.async_redis_token_bucket import AsyncRedisTokenBucket
from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_leaky_bucket import RedisLeakyBucket
from src.algorithms.redis_sliding_window_counter import RedisSlidingWindowCounter
from src.algorithms.redis_sliding_window_log import RedisSlidingWindowLog
from src.algorithms.redis_token_bucket import RedisTokenBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket
from src.middleware.circuit_breaker import CircuitBreaker
from src.middleware.config import API_KEYS, DEFAULT_ROUTE_RULES, EndpointRule
from src.middleware.endpoint_trie import EndpointTrie
from src.monitoring.logging_config import app_logger
from src.monitoring.metrics import (
    ACTIVE_REQUESTS,
    BLOCKED_REQUESTS,
    LIMITER_OVERHEAD,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from src.monitoring.tracing import trace_rate_limiter_evaluation


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Production rate limiting middleware for ASGI applications.

    Attributes:
        app: The ASGI application callable.
        default_limiter: Optional global fallback limiter instance.
        rules: Mapping from route paths to EndpointRule configurations.
        api_keys: Registered API keys with tier multipliers.
        circuit_breaker: CircuitBreaker instance for fail-open resilience.
        redis_client: Optional sync Redis client for distributed state synchronization.
        async_redis_client: Optional async Redis client for non-blocking event loop execution.
    """

    def __init__(
        self,
        app,
        default_limiter=None,
        rules: dict[str, EndpointRule] | None = None,
        api_keys: dict[str, dict] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        redis_client: Any | None = None,
        async_redis_client: Any | None = None,
    ):
        super().__init__(app)
        self.redis_client = redis_client
        self.async_redis_client = async_redis_client

        # Detect if redis_client passed is actually an async client
        if redis_client is not None and (
            inspect.iscoroutinefunction(getattr(redis_client, "ping", None))
            or inspect.iscoroutinefunction(getattr(redis_client, "get", None))
        ):
            self.async_redis_client = redis_client
            self.redis_client = None

        if default_limiter:
            self.default_limiter = default_limiter
        elif self.async_redis_client:
            self.default_limiter = AsyncRedisTokenBucket(
                self.async_redis_client, capacity=100, refill_rate_per_sec=10.0
            )
        elif self.redis_client:
            self.default_limiter = RedisTokenBucket(
                self.redis_client, capacity=100, refill_rate_per_sec=10.0
            )
        else:
            self.default_limiter = TokenBucket(capacity=100, refill_rate_per_sec=10.0)

        self.api_keys = api_keys or API_KEYS
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5, recovery_timeout=30.0, fail_open=True
        )

        # Build EndpointTrie for O(K) prefix matching
        initial_rules = rules or DEFAULT_ROUTE_RULES
        default_rule = initial_rules.get(
            "default", EndpointRule(limit=100, window_seconds=60)
        )
        self.trie = EndpointTrie(default_rule=default_rule)
        for route_path, rule in initial_rules.items():
            if route_path != "default":
                self.trie.insert(route_path, rule)

        # Per-route limiter cache: (cache_key) -> algorithm instance
        self._limiter_cache: dict[str, Any] = {}

    def _get_client_identity(self, request: Request) -> tuple[str, str, int]:
        """Resolves (client_id, tier, limit_multiplier).

        Checks X-API-Key header first; falls back to client IP.
        """
        api_key = request.headers.get("x-api-key")
        if api_key and api_key in self.api_keys:
            tier_info = self.api_keys[api_key]
            return api_key, tier_info["tier"], tier_info["limit_multiplier"]

        # Fallback to IP address
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            ip = forwarded_for.split(",")[0].strip()
        elif request.client:
            ip = request.client.host
        else:
            ip = "unknown_client"

        return f"ip_{ip}", "anonymous", 1

    def _get_limiter_for_route(self, path: str, multiplier: int):
        rule = self.trie.match(path)

        effective_limit = rule.limit * multiplier
        backend_tag = (
            "async_redis"
            if self.async_redis_client
            else "redis" if self.redis_client else "memory"
        )
        cache_key = f"{path}:{rule.algorithm}:{effective_limit}:{rule.window_seconds}:{backend_tag}"

        if cache_key not in self._limiter_cache:
            if self.async_redis_client:
                if rule.algorithm == "fixed_window":
                    limiter = AsyncRedisFixedWindow(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "sliding_window_log":
                    limiter = AsyncRedisSlidingWindowLog(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "sliding_window_counter":
                    limiter = AsyncRedisSlidingWindowCounter(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "leaky_bucket":
                    leak_rate = effective_limit / rule.window_seconds
                    limiter = AsyncRedisLeakyBucket(
                        self.async_redis_client,
                        capacity=effective_limit,
                        leak_rate_per_sec=leak_rate,
                    )
                else:  # default token_bucket
                    refill_rate = effective_limit / rule.window_seconds
                    limiter = AsyncRedisTokenBucket(
                        self.async_redis_client,
                        capacity=effective_limit,
                        refill_rate_per_sec=refill_rate,
                    )
            elif self.redis_client:
                if rule.algorithm == "fixed_window":
                    limiter = RedisFixedWindow(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "sliding_window_log":
                    limiter = RedisSlidingWindowLog(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "sliding_window_counter":
                    limiter = RedisSlidingWindowCounter(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                    )
                elif rule.algorithm == "leaky_bucket":
                    leak_rate = effective_limit / rule.window_seconds
                    limiter = RedisLeakyBucket(
                        self.redis_client,
                        capacity=effective_limit,
                        leak_rate_per_sec=leak_rate,
                    )
                else:  # default token_bucket
                    refill_rate = effective_limit / rule.window_seconds
                    limiter = RedisTokenBucket(
                        self.redis_client,
                        capacity=effective_limit,
                        refill_rate_per_sec=refill_rate,
                    )
            else:
                if rule.algorithm == "fixed_window":
                    limiter = FixedWindowCounter(
                        limit=effective_limit, window_seconds=rule.window_seconds
                    )
                elif rule.algorithm == "sliding_window_log":
                    limiter = SlidingWindowLog(
                        limit=effective_limit, window_seconds=rule.window_seconds
                    )
                elif rule.algorithm == "sliding_window_counter":
                    limiter = SlidingWindowCounter(
                        limit=effective_limit, window_seconds=rule.window_seconds
                    )
                elif rule.algorithm == "leaky_bucket":
                    leak_rate = effective_limit / rule.window_seconds
                    limiter = LeakyBucket(
                        capacity=effective_limit, leak_rate_per_sec=leak_rate
                    )
                else:  # default token_bucket
                    refill_rate = effective_limit / rule.window_seconds
                    limiter = TokenBucket(
                        capacity=effective_limit, refill_rate_per_sec=refill_rate
                    )

            self._limiter_cache[cache_key] = limiter

        return self._limiter_cache[cache_key], effective_limit, rule.algorithm

    async def _safe_remaining(self, limiter: Any, client_id: str, default: int) -> int:
        func = getattr(limiter, "remaining", getattr(limiter, "get_remaining", None))
        if func is None:
            return default
        try:
            if inspect.iscoroutinefunction(func):
                return await func(client_id)
            return func(client_id)
        except Exception:  # noqa: BLE001
            return default

    async def _safe_retry_after(self, limiter: Any, client_id: str) -> int:
        func = getattr(
            limiter, "retry_after", getattr(limiter, "get_retry_after", None)
        )
        if func is None:
            return 1
        try:
            if inspect.iscoroutinefunction(func):
                return await func(client_id)
            return func(client_id)
        except Exception:  # noqa: BLE001
            return 1

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Telemetry / metrics endpoint bypasses rate limiting
        if path == "/metrics":
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        ACTIVE_REQUESTS.inc()
        start_time = time.perf_counter()
        try:
            client_id, tier, multiplier = self._get_client_identity(request)
            limiter, nominal_limit, algorithm_name = self._get_limiter_for_route(
                path, multiplier
            )

            # Wrap rate evaluation in distributed trace span and circuit breaker
            with trace_rate_limiter_evaluation(
                algorithm=algorithm_name,
                client_id=client_id,
                tier=tier,
                endpoint=path,
            ) as trace_data:
                limiter_start = time.perf_counter()
                is_coro = inspect.iscoroutinefunction(limiter.is_allowed)
                if is_coro:
                    is_allowed = await self.circuit_breaker.async_call(
                        limiter.is_allowed, client_id, fallback=True
                    )
                else:
                    is_allowed = self.circuit_breaker.call(
                        limiter.is_allowed, client_id, fallback=True
                    )
                limiter_overhead = time.perf_counter() - limiter_start
                LIMITER_OVERHEAD.labels(algorithm=algorithm_name, tier=tier).observe(
                    limiter_overhead
                )

                trace_data["allowed"] = is_allowed

                if not is_allowed:
                    remaining = 0
                    trace_data["remaining"] = remaining
                    retry_after = await self._safe_retry_after(limiter, client_id)
                    headers = {
                        "X-RateLimit-Limit": str(nominal_limit),
                        "X-RateLimit-Remaining": str(remaining),
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Tier": tier,
                        "X-Request-ID": request_id,
                    }
                    elapsed = time.perf_counter() - start_time
                    REQUEST_COUNT.labels(
                        endpoint=path,
                        status="blocked",
                        algorithm=algorithm_name,
                        tier=tier,
                    ).inc()
                    BLOCKED_REQUESTS.labels(
                        endpoint=path, tier=tier, algorithm=algorithm_name
                    ).inc()
                    REQUEST_LATENCY.labels(endpoint=path, status="blocked").observe(elapsed)

                    # Emit structured JSON log event for Loki
                    app_logger.warning(
                        "Rate limit quota exceeded",
                        extra={
                            "request_id": request_id,
                            "client_id": client_id,
                            "tier": tier,
                            "algorithm": algorithm_name,
                            "endpoint": path,
                            "method": request.method,
                            "status_code": 429,
                            "latency_ms": round(elapsed * 1000, 2),
                            "limiter_overhead_ms": round(limiter_overhead * 1000, 3),
                            "retry_after": retry_after,
                            "remaining": 0,
                        },
                    )

                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "rate limit exceeded",
                            "detail": f"Quota of {nominal_limit} requests exceeded.",
                            "retry_after": retry_after,
                        },
                        headers=headers,
                    )

            response = await call_next(request)
            elapsed = time.perf_counter() - start_time
            REQUEST_COUNT.labels(
                endpoint=path,
                status="allowed",
                algorithm=algorithm_name,
                tier=tier,
            ).inc()
            REQUEST_LATENCY.labels(endpoint=path, status="allowed").observe(elapsed)

            # Attach rate limit headers to all successful/downstream responses
            try:
                remaining = await self._safe_remaining(
                    limiter, client_id, nominal_limit
                )
                retry_after = await self._safe_retry_after(limiter, client_id)
            except Exception:  # noqa: BLE001
                remaining = nominal_limit
                retry_after = 0

            response.headers["X-RateLimit-Limit"] = str(nominal_limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Tier"] = tier
            response.headers["X-Request-ID"] = request_id

            # Emit structured JSON log event for Loki
            app_logger.info(
                "Request permitted",
                extra={
                    "request_id": request_id,
                    "client_id": client_id,
                    "tier": tier,
                    "algorithm": algorithm_name,
                    "endpoint": path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "latency_ms": round(elapsed * 1000, 2),
                    "limiter_overhead_ms": round(limiter_overhead * 1000, 3),
                    "remaining": remaining,
                },
            )

            return response
        finally:
            ACTIVE_REQUESTS.dec()
