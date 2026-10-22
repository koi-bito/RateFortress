"""FastAPI / Starlette Rate Limiting Middleware for RateFortress.

Inspects incoming HTTP requests, resolves client identity (via API Key or IP),
evaluates rate limit quotas, attaches standard rate limit headers,
and returns HTTP 429 Too Many Requests upon limit violations.
"""

from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket
from src.middleware.config import API_KEYS, DEFAULT_ROUTE_RULES, EndpointRule


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Production rate limiting middleware for ASGI applications.

    Attributes:
        app: The ASGI application callable.
        default_limiter: Optional global fallback limiter instance.
        rules: Mapping from route paths to EndpointRule configurations.
        api_keys: Registered API keys with tier multipliers.
    """

    def __init__(
        self,
        app,
        default_limiter=None,
        rules: dict[str, EndpointRule] | None = None,
        api_keys: dict[str, dict] | None = None,
    ):
        super().__init__(app)
        self.default_limiter = default_limiter or TokenBucket(
            capacity=100, refill_rate_per_sec=10.0
        )
        self.rules = rules or DEFAULT_ROUTE_RULES
        self.api_keys = api_keys or API_KEYS

        # Per-route limiter cache: (path, effective_limit) -> algorithm instance
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
        rule = self.rules.get(path, self.rules.get("default"))
        if not rule:
            return self.default_limiter, self.default_limiter.limit

        effective_limit = rule.limit * multiplier
        cache_key = f"{path}:{rule.algorithm}:{effective_limit}:{rule.window_seconds}"

        if cache_key not in self._limiter_cache:
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

        return self._limiter_cache[cache_key], effective_limit

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_id, tier, multiplier = self._get_client_identity(request)
        path = request.url.path

        limiter, nominal_limit = self._get_limiter_for_route(path, multiplier)

        is_allowed = limiter.is_allowed(client_id)
        remaining = limiter.get_remaining(client_id)
        retry_after = limiter.get_retry_after(client_id)

        if not is_allowed:
            headers = {
                "X-RateLimit-Limit": str(nominal_limit),
                "X-RateLimit-Remaining": "0",
                "Retry-After": str(retry_after),
                "X-RateLimit-Tier": tier,
            }
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

        # Attach rate limit headers to all successful and non-429 responses
        response.headers["X-RateLimit-Limit"] = str(nominal_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["Retry-After"] = str(retry_after)
        response.headers["X-RateLimit-Tier"] = tier

        return response
