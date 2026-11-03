"""FastAPI / Starlette Rate Limiting Middleware for RateFortress.

Inspects incoming HTTP requests, resolves client identity (via API Key or IP),
matches hierarchical endpoint rules using an EndpointTrie, enforces rate quotas,
protects against backend crashes via CircuitBreaker fail-open resilience,
and attaches standard rate limit headers (X-RateLimit-Limit, Remaining, Retry-After).

Supports both synchronous and non-blocking asynchronous Redis algorithms,
preventing event loop thread blocking under high concurrent loads.
"""

import asyncio
import inspect
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.algorithms.async_redis_fixed_window import AsyncRedisFixedWindow
from src.algorithms.async_redis_gcra import AsyncRedisGCRA
from src.algorithms.async_redis_leaky_bucket import AsyncRedisLeakyBucket
from src.algorithms.async_redis_sliding_window_counter import (
    AsyncRedisSlidingWindowCounter,
)
from src.algorithms.async_redis_sliding_window_log import AsyncRedisSlidingWindowLog
from src.algorithms.async_redis_token_bucket import AsyncRedisTokenBucket
from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.redis_fixed_window import RedisFixedWindow
from src.algorithms.redis_gcra import RedisGCRA
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
from src.middleware.key_manager import APIKeyManager
from src.middleware.priority_queue import PriorityRequestQueue
from src.middleware.trusted_proxy import parse_trusted_proxies, resolve_client_ip
from src.monitoring.logging_config import app_logger
from src.monitoring.metrics import (
    ACTIVE_REQUESTS,
    BLOCKED_REQUESTS,
    LIMITER_OVERHEAD,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from src.monitoring.tracing import trace_rate_limiter_evaluation

TIER_PRIORITY_MAP: dict[str, int] = {
    "enterprise": PriorityRequestQueue.PRIORITY_ENTERPRISE,
    "paid": PriorityRequestQueue.PRIORITY_PAID,
    "free": PriorityRequestQueue.PRIORITY_FREE,
    "anonymous": PriorityRequestQueue.PRIORITY_ANONYMOUS,
}


def format_compound_key(api_key: str | None, endpoint: str, ip: str) -> str:
    """Formats a multi-dimensional compound rate limiting key combining identity, route, and network IP.

    Format: {api_key or 'anon'}:{endpoint}:{ip}
    """
    key_part = api_key or "anon"
    clean_endpoint = endpoint.strip("/").replace("/", "_") or "root"
    return f"{key_part}:{clean_endpoint}:{ip}"


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
        priority_queue: PriorityRequestQueue instance for load shedding and tier prioritization.
        saturation_threshold: Concurrent in-flight request threshold before queuing/shedding triggers.
        max_queue_depth: Maximum requests held in the priority queue before dropping.
        queue_timeout: Maximum seconds a prioritized request will wait in queue before timing out.
        shed_free_tier: Whether free-tier requests are shed immediately under saturation.
        global_ip_limit: Global rate limit quota across all endpoints per IP (Day 141 compound key).
        global_ip_window: Window duration in seconds for global per-IP limiting.
        global_ip_algorithm: Algorithm used for global per-IP limiting.
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
        trusted_proxies: str | None = None,
        key_manager: APIKeyManager | None = None,
        priority_queue: PriorityRequestQueue | None = None,
        saturation_threshold: int | None = None,
        max_queue_depth: int | None = None,
        queue_timeout: float | None = None,
        shed_free_tier: bool | None = None,
        global_ip_limit: int | None = None,
        global_ip_window: int | None = None,
        global_ip_algorithm: str = "fixed_window",
    ):
        super().__init__(app)
        self.redis_client = redis_client
        self.async_redis_client = async_redis_client
        self.trusted_proxies = parse_trusted_proxies(trusted_proxies)
        self.key_manager = key_manager

        # Priority request queue and saturation configuration
        self.priority_queue = priority_queue or PriorityRequestQueue()
        self.saturation_threshold = (
            saturation_threshold
            if saturation_threshold is not None
            else int(
                os.getenv(
                    "RATEFORTRESS_SATURATION_THRESHOLD",
                    os.getenv("SATURATION_THRESHOLD", "100"),
                )
            )
        )
        self.max_queue_depth = (
            max_queue_depth
            if max_queue_depth is not None
            else int(
                os.getenv(
                    "RATEFORTRESS_MAX_QUEUE_DEPTH",
                    os.getenv("MAX_QUEUE_DEPTH", "100"),
                )
            )
        )
        self.queue_timeout = (
            queue_timeout
            if queue_timeout is not None
            else float(
                os.getenv(
                    "RATEFORTRESS_QUEUE_TIMEOUT",
                    os.getenv("QUEUE_TIMEOUT", "5.0"),
                )
            )
        )
        self.shed_free_tier = (
            shed_free_tier
            if shed_free_tier is not None
            else os.getenv("RATEFORTRESS_SHED_FREE_TIER", "true").lower()
            in ("1", "true", "yes")
        )
        self._active_requests = 0
        self._active_waiters = 0
        self.is_shutting_down = False

        # Day 141 Compound Key: Global per-IP rate limiting configuration
        self.global_ip_limit = (
            global_ip_limit
            if global_ip_limit is not None
            else (int(os.getenv("RATEFORTRESS_GLOBAL_IP_LIMIT", "0")) or None)
        )
        self.global_ip_window = (
            global_ip_window
            if global_ip_window is not None
            else int(os.getenv("RATEFORTRESS_GLOBAL_IP_WINDOW", "60"))
        )
        self.global_ip_algorithm = global_ip_algorithm or "fixed_window"
        self.global_ip_limiter = self._create_global_ip_limiter()

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

    def _create_global_ip_limiter(self) -> Any:
        """Instantiates the global per-IP limiter matching the active storage backend."""
        if not self.global_ip_limit:
            return None

        algo = self.global_ip_algorithm
        limit = self.global_ip_limit
        win = self.global_ip_window
        ns = "global_ip"

        if self.async_redis_client:
            if algo == "sliding_window_counter":
                return AsyncRedisSlidingWindowCounter(
                    self.async_redis_client, limit=limit, window_seconds=win, namespace=ns
                )
            elif algo == "sliding_window_log":
                return AsyncRedisSlidingWindowLog(
                    self.async_redis_client, limit=limit, window_seconds=win, namespace=ns
                )
            elif algo == "token_bucket":
                return AsyncRedisTokenBucket(
                    self.async_redis_client,
                    capacity=limit,
                    refill_rate=float(limit) / float(win),
                    namespace=ns,
                )
            elif algo == "leaky_bucket":
                return AsyncRedisLeakyBucket(
                    self.async_redis_client,
                    capacity=limit,
                    leak_rate=float(limit) / float(win),
                    namespace=ns,
                )
            elif algo in ("gcra", "cell_rate"):
                return AsyncRedisGCRA(
                    self.async_redis_client, limit=limit, period=float(win), namespace=ns
                )
            else:
                return AsyncRedisFixedWindow(
                    self.async_redis_client, limit=limit, window_seconds=win, namespace=ns
                )
        elif self.redis_client:
            if algo == "sliding_window_counter":
                return RedisSlidingWindowCounter(
                    self.redis_client, limit=limit, window_seconds=win, namespace=ns
                )
            elif algo == "sliding_window_log":
                return RedisSlidingWindowLog(
                    self.redis_client, limit=limit, window_seconds=win, namespace=ns
                )
            elif algo == "token_bucket":
                return RedisTokenBucket(
                    self.redis_client,
                    capacity=limit,
                    refill_rate_per_sec=float(limit) / float(win),
                    namespace=ns,
                )
            elif algo == "leaky_bucket":
                return RedisLeakyBucket(
                    self.redis_client,
                    capacity=limit,
                    leak_rate_per_sec=float(limit) / float(win),
                    namespace=ns,
                )
            elif algo in ("gcra", "cell_rate"):
                return RedisGCRA(
                    self.redis_client, limit=limit, period=float(win), namespace=ns
                )
            else:
                return RedisFixedWindow(
                    self.redis_client, limit=limit, window_seconds=win, namespace=ns
                )
        else:
            if algo == "sliding_window_counter":
                return SlidingWindowCounter(limit=limit, window_seconds=win)
            elif algo == "sliding_window_log":
                return SlidingWindowLog(limit=limit, window_seconds=win)
            elif algo == "token_bucket":
                return TokenBucket(
                    capacity=limit, refill_rate_per_sec=float(limit) / float(win)
                )
            elif algo == "leaky_bucket":
                return LeakyBucket(
                    capacity=limit, leak_rate_per_sec=float(limit) / float(win)
                )
            elif algo in ("gcra", "cell_rate"):
                return GCRA(limit=limit, period=float(win))
            else:
                return FixedWindowCounter(limit=limit, window_seconds=win)

    def _resolve_ip(self, request: Request) -> str:
        """Resolves client IP with anti-spoofing trusted proxy validation."""
        peer_ip = request.client.host if request.client else "unknown_client"
        forwarded_for = request.headers.get("x-forwarded-for")
        return resolve_client_ip(
            peer_ip=peer_ip,
            forwarded_for=forwarded_for,
            trusted_networks=self.trusted_proxies,
        )

    def _get_client_identity(self, request: Request) -> tuple[str, str, int]:
        """Resolves (client_id, tier, limit_multiplier).

        Checks X-API-Key header first; falls back to client IP.
        """
        api_key = request.headers.get("x-api-key")
        if api_key:
            if self.key_manager is not None:
                meta = self.key_manager.verify_key(api_key)
                if meta:
                    return api_key, meta.tier, meta.limit_multiplier
            elif self.api_keys and api_key in self.api_keys:
                tier_info = self.api_keys[api_key]
                return api_key, tier_info["tier"], tier_info["limit_multiplier"]

        ip = self._resolve_ip(request)
        return f"ip_{ip}", "anonymous", 1

    def _get_limiter_for_route(self, path: str, multiplier: int):
        rule, matched_pattern = self.trie.match_with_pattern(path)

        effective_limit = rule.limit * multiplier
        backend_tag = (
            "async_redis"
            if self.async_redis_client
            else "redis" if self.redis_client else "memory"
        )
        cache_key = f"{matched_pattern}:{rule.algorithm}:{effective_limit}:{rule.window_seconds}:{backend_tag}"

        # Clean namespace for Redis key scoping
        clean_ns = matched_pattern.strip("/").replace("/", "_").replace("*", "wildcard") or "root"
        namespace = f"route_{clean_ns}"

        if cache_key not in self._limiter_cache:
            if self.async_redis_client:
                if rule.algorithm == "fixed_window":
                    limiter = AsyncRedisFixedWindow(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "sliding_window_log":
                    limiter = AsyncRedisSlidingWindowLog(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "sliding_window_counter":
                    limiter = AsyncRedisSlidingWindowCounter(
                        self.async_redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "leaky_bucket":
                    leak_rate = effective_limit / rule.window_seconds
                    limiter = AsyncRedisLeakyBucket(
                        self.async_redis_client,
                        capacity=effective_limit,
                        leak_rate_per_sec=leak_rate,
                        namespace=namespace,
                    )
                elif rule.algorithm in ("gcra", "cell_rate"):
                    limiter = AsyncRedisGCRA(
                        self.async_redis_client,
                        limit=effective_limit,
                        period=rule.window_seconds,
                        namespace=namespace,
                    )
                else:  # default token_bucket
                    refill_rate = effective_limit / rule.window_seconds
                    limiter = AsyncRedisTokenBucket(
                        self.async_redis_client,
                        capacity=effective_limit,
                        refill_rate_per_sec=refill_rate,
                        namespace=namespace,
                    )
            elif self.redis_client:
                if rule.algorithm == "fixed_window":
                    limiter = RedisFixedWindow(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "sliding_window_log":
                    limiter = RedisSlidingWindowLog(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "sliding_window_counter":
                    limiter = RedisSlidingWindowCounter(
                        self.redis_client,
                        limit=effective_limit,
                        window_seconds=rule.window_seconds,
                        namespace=namespace,
                    )
                elif rule.algorithm == "leaky_bucket":
                    leak_rate = effective_limit / rule.window_seconds
                    limiter = RedisLeakyBucket(
                        self.redis_client,
                        capacity=effective_limit,
                        leak_rate_per_sec=leak_rate,
                        namespace=namespace,
                    )
                elif rule.algorithm in ("gcra", "cell_rate"):
                    limiter = RedisGCRA(
                        self.redis_client,
                        limit=effective_limit,
                        period=rule.window_seconds,
                        namespace=namespace,
                    )
                else:  # default token_bucket
                    refill_rate = effective_limit / rule.window_seconds
                    limiter = RedisTokenBucket(
                        self.redis_client,
                        capacity=effective_limit,
                        refill_rate_per_sec=refill_rate,
                        namespace=namespace,
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
                elif rule.algorithm in ("gcra", "cell_rate"):
                    limiter = GCRA(
                        limit=effective_limit, period=rule.window_seconds
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
        except Exception:
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
        except Exception:
            return 1

    def _release_slot(self) -> None:
        """Releases an active request slot and admits the highest-priority queued waiter."""
        self._active_requests = max(0, self._active_requests - 1)
        while not self.priority_queue.is_empty():
            entry = self.priority_queue.pop()
            if entry is None:
                break
            _, _, _, waiter = entry
            if waiter is not None and not waiter.done():
                self._active_requests += 1
                waiter.set_result(True)
                break

    def _shed_response(
        self,
        request_id: str,
        tier: str,
        nominal_limit: int,
        retry_after: int = 1,
        detail: str = "System is saturated. Request shed.",
    ) -> JSONResponse:
        """Constructs an RFC-compliant HTTP 503 response for shed requests."""
        headers = {
            "X-RateLimit-Limit": str(nominal_limit),
            "X-RateLimit-Remaining": "0",
            "Retry-After": str(retry_after),
            "X-RateLimit-Tier": tier,
            "X-Request-ID": request_id,
        }
        app_logger.warning(
            "Request shed due to system saturation",
            extra={
                "request_id": request_id,
                "tier": tier,
                "status_code": 503,
                "detail": detail,
                "retry_after": retry_after,
            },
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": "service unavailable",
                "detail": detail,
                "retry_after": retry_after,
            },
            headers=headers,
        )

    async def drain_in_flight(self, timeout: float = 10.0, poll_interval: float = 0.05) -> bool:
        """Waits for active in-flight requests to complete up to timeout."""
        deadline = time.time() + timeout
        while self._active_requests > 0:
            if time.time() >= deadline:
                return False
            await asyncio.sleep(poll_interval)
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        app_ref = getattr(request, "app", None)
        if app_ref is not None and hasattr(app_ref, "state") and not hasattr(app_ref.state, "rate_limit_middleware"):
            app_ref.state.rate_limit_middleware = self

        # Day 143: Reject new traffic during graceful shutdown while allowing in-flight requests to drain
        is_shutting_down = self.is_shutting_down or (
            app_ref is not None and getattr(getattr(app_ref, "state", None), "is_shutting_down", False)
        )
        if is_shutting_down and path not in ("/health", "/health/ready"):
            req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
            return JSONResponse(
                status_code=503,
                content={
                    "error": "service unavailable",
                    "detail": "Server is shutting down. In-flight requests draining.",
                    "retry_after": 5,
                },
                headers={"Retry-After": "5", "X-Request-ID": req_id},
            )

        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        ACTIVE_REQUESTS.inc()
        start_time = time.perf_counter()
        slot_acquired = False
        try:
            client_id, tier, multiplier = self._get_client_identity(request)
            client_ip = self._resolve_ip(request)
            limiter, nominal_limit, algorithm_name = self._get_limiter_for_route(
                path, multiplier
            )

            # Option B: Shedding-under-saturation
            # shortcut: in-memory PriorityRequestQueue is single-process, upgrade to Redis Sorted Set (ZSET) if distributed priority queuing across multiple gateway instances is required.
            if self._active_requests < self.saturation_threshold:
                self._active_requests += 1
                slot_acquired = True
            else:
                if self.shed_free_tier and tier in ("free", "anonymous"):
                    elapsed = time.perf_counter() - start_time
                    REQUEST_COUNT.labels(
                        endpoint=path,
                        status="shed",
                        algorithm=algorithm_name,
                        tier=tier,
                    ).inc()
                    REQUEST_LATENCY.labels(endpoint=path, status="shed").observe(elapsed)
                    return self._shed_response(
                        request_id=request_id,
                        tier=tier,
                        nominal_limit=nominal_limit,
                        retry_after=1,
                        detail="System is saturated. Free-tier request shed.",
                    )

                if self._active_waiters >= self.max_queue_depth:
                    elapsed = time.perf_counter() - start_time
                    REQUEST_COUNT.labels(
                        endpoint=path,
                        status="shed",
                        algorithm=algorithm_name,
                        tier=tier,
                    ).inc()
                    REQUEST_LATENCY.labels(endpoint=path, status="shed").observe(elapsed)
                    return self._shed_response(
                        request_id=request_id,
                        tier=tier,
                        nominal_limit=nominal_limit,
                        retry_after=1,
                        detail="Priority queue capacity exceeded. Request shed.",
                    )

                loop = asyncio.get_running_loop()
                waiter = loop.create_future()
                priority = TIER_PRIORITY_MAP.get(
                    tier, PriorityRequestQueue.PRIORITY_ANONYMOUS
                )
                self._active_waiters += 1
                self.priority_queue.push(priority, request_id, waiter)
                try:
                    await asyncio.wait_for(waiter, timeout=self.queue_timeout)
                    slot_acquired = True
                except (TimeoutError, asyncio.CancelledError):
                    if (
                        waiter.done()
                        and not waiter.cancelled()
                        and waiter.exception() is None
                    ):
                        self._release_slot()
                    elapsed = time.perf_counter() - start_time
                    REQUEST_COUNT.labels(
                        endpoint=path,
                        status="shed",
                        algorithm=algorithm_name,
                        tier=tier,
                    ).inc()
                    REQUEST_LATENCY.labels(endpoint=path, status="shed").observe(elapsed)
                    return self._shed_response(
                        request_id=request_id,
                        tier=tier,
                        nominal_limit=nominal_limit,
                        retry_after=1,
                        detail="Request timed out waiting in priority queue.",
                    )
                finally:
                    self._active_waiters -= 1

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
                        "X-RateLimit-Scope": "key" if client_id != f"ip_{client_ip}" else "ip",
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
                            "scope": "key" if client_id != f"ip_{client_ip}" else "ip",
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

                # Secondary dimension: global per-IP limit check (ANDed)
                if self.global_ip_limiter is not None:
                    ip_key = f"ip_{client_ip}"
                    is_ip_coro = inspect.iscoroutinefunction(
                        self.global_ip_limiter.is_allowed
                    )
                    if is_ip_coro:
                        ip_allowed = await self.circuit_breaker.async_call(
                            self.global_ip_limiter.is_allowed, ip_key, fallback=True
                        )
                    else:
                        ip_allowed = self.circuit_breaker.call(
                            self.global_ip_limiter.is_allowed, ip_key, fallback=True
                        )

                    if not ip_allowed:
                        ip_retry_after = await self._safe_retry_after(
                            self.global_ip_limiter, ip_key
                        )
                        headers = {
                            "X-RateLimit-Limit": str(self.global_ip_limit),
                            "X-RateLimit-Remaining": "0",
                            "Retry-After": str(ip_retry_after),
                            "X-RateLimit-Tier": tier,
                            "X-RateLimit-Scope": "ip",
                            "X-Request-ID": request_id,
                        }
                        elapsed = time.perf_counter() - start_time
                        REQUEST_COUNT.labels(
                            endpoint=path,
                            status="blocked",
                            algorithm=self.global_ip_algorithm,
                            tier=tier,
                        ).inc()
                        BLOCKED_REQUESTS.labels(
                            endpoint=path, tier=tier, algorithm=self.global_ip_algorithm
                        ).inc()
                        REQUEST_LATENCY.labels(endpoint=path, status="blocked").observe(elapsed)

                        app_logger.warning(
                            "Global IP rate limit quota exceeded",
                            extra={
                                "request_id": request_id,
                                "client_id": ip_key,
                                "tier": tier,
                                "algorithm": self.global_ip_algorithm,
                                "endpoint": path,
                                "method": request.method,
                                "status_code": 429,
                                "latency_ms": round(elapsed * 1000, 2),
                                "retry_after": ip_retry_after,
                                "remaining": 0,
                                "scope": "ip",
                            },
                        )

                        return JSONResponse(
                            status_code=429,
                            content={
                                "error": "rate limit exceeded",
                                "detail": f"Global IP quota of {self.global_ip_limit} requests exceeded for IP {client_ip}.",
                                "retry_after": ip_retry_after,
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
            except Exception:
                remaining = nominal_limit

            stricter_limit = nominal_limit
            stricter_remaining = remaining
            scope_label = "key" if client_id != f"ip_{client_ip}" else "ip"

            if self.global_ip_limiter is not None:
                try:
                    ip_key = f"ip_{client_ip}"
                    ip_rem = await self._safe_remaining(
                        self.global_ip_limiter, ip_key, self.global_ip_limit
                    )
                    response.headers["X-RateLimit-IP-Limit"] = str(self.global_ip_limit)
                    response.headers["X-RateLimit-IP-Remaining"] = str(ip_rem)
                    if ip_rem < remaining:
                        stricter_remaining = ip_rem
                        stricter_limit = self.global_ip_limit
                        scope_label = "ip"
                except Exception as exc:
                    app_logger.debug("Could not resolve IP remaining quota: %s", exc)

            response.headers["X-RateLimit-Limit"] = str(stricter_limit)
            response.headers["X-RateLimit-Remaining"] = str(stricter_remaining)
            # RFC 6585: Retry-After is reserved for 429 / 503 responses (or when remaining quota is exhausted)
            if stricter_remaining == 0:
                retry_after = await self._safe_retry_after(limiter, client_id)
                response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Tier"] = tier
            response.headers["X-RateLimit-Scope"] = scope_label
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
            if slot_acquired:
                self._release_slot()
            ACTIVE_REQUESTS.dec()
