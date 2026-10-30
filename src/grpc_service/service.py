"""gRPC RateLimiter service implementation for RateFortress.

Allows high-throughput internal microservices to evaluate rate limits over
binary Protocol Buffers / HTTP/2 transport instead of REST/JSON.
"""

from __future__ import annotations

import logging
from concurrent import futures
from typing import Any

import grpc

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket
from src.grpc_service import ratefortress_pb2, ratefortress_pb2_grpc

logger = logging.getLogger("ratefortress.grpc")

TIER_MULTIPLIERS: dict[str, int] = {
    "free": 1,
    "paid": 10,
    "enterprise": 50,
    "anonymous": 1,
}

BASE_LIMITS: dict[str, int] = {
    "default": 10,
    "/api/test": 10,
    "/api/expensive-endpoint": 2,
    "/api/admin": 100,
}


class RateLimiterService(ratefortress_pb2_grpc.RateLimiterServicer):
    """gRPC Servicer managing distributed rate-limiting requests."""

    def __init__(self, default_algorithm: str = "token_bucket"):
        self.default_algorithm = default_algorithm
        self._limiters: dict[str, Any] = {}

    def _get_limiter(self, key: str, algorithm: str, limit: int, window_seconds: int = 10):
        if key not in self._limiters:
            algo = algorithm.lower().strip() or self.default_algorithm
            if algo in ("token_bucket", "tokenbucket"):
                self._limiters[key] = TokenBucket(
                    capacity=limit, refill_rate_per_sec=float(limit) / float(window_seconds)
                )
            elif algo in ("gcra", "cell_rate"):
                self._limiters[key] = GCRA(limit=limit, period=float(window_seconds))
            elif algo in ("sliding_window_log", "swl"):
                self._limiters[key] = SlidingWindowLog(limit=limit, window_seconds=window_seconds)
            elif algo in ("sliding_window_counter", "swc"):
                self._limiters[key] = SlidingWindowCounter(limit=limit, window_seconds=window_seconds)
            elif algo in ("leaky_bucket", "lb"):
                self._limiters[key] = LeakyBucket(
                    capacity=limit, leak_rate_per_sec=float(limit) / float(window_seconds)
                )
            else:
                self._limiters[key] = FixedWindowCounter(limit=limit, window_seconds=window_seconds)
        return self._limiters[key]

    def CheckRateLimit(
        self, request: ratefortress_pb2.RateLimitRequest, context: grpc.ServicerContext
    ) -> ratefortress_pb2.RateLimitResponse:
        client_id = request.client_id or "anonymous"
        endpoint = request.endpoint or "default"
        tier = (request.tier or "free").lower()
        algorithm = request.algorithm or self.default_algorithm
        cost = max(1, request.cost or 1)

        base_limit = BASE_LIMITS.get(endpoint, BASE_LIMITS["default"])
        multiplier = TIER_MULTIPLIERS.get(tier, 1)
        effective_limit = base_limit * multiplier

        limiter_key = f"{endpoint}:{tier}:{algorithm}"
        limiter = self._get_limiter(limiter_key, algorithm, effective_limit, window_seconds=10)

        # Evaluate rate limiting
        allowed = limiter.is_allowed(client_id, cost)
        remaining = limiter.get_remaining(client_id) if hasattr(limiter, "get_remaining") else 0
        retry_after = limiter.get_retry_after(client_id) if hasattr(limiter, "get_retry_after") else (0 if allowed else 1)

        return ratefortress_pb2.RateLimitResponse(
            allowed=allowed,
            remaining=remaining,
            retry_after_seconds=retry_after,
            limit=effective_limit,
        )

    def GetQuota(
        self, request: ratefortress_pb2.QuotaRequest, context: grpc.ServicerContext
    ) -> ratefortress_pb2.QuotaResponse:
        client_id = request.client_id or "anonymous"
        endpoint = request.endpoint or "default"
        algorithm = request.algorithm or self.default_algorithm
        base_limit = BASE_LIMITS.get(endpoint, BASE_LIMITS["default"])

        limiter_key = f"{endpoint}:free:{algorithm}"
        limiter = self._get_limiter(limiter_key, algorithm, base_limit, window_seconds=10)

        remaining = limiter.get_remaining(client_id) if hasattr(limiter, "get_remaining") else base_limit

        return ratefortress_pb2.QuotaResponse(
            limit=base_limit,
            remaining=remaining,
        )


def create_grpc_server(
    host: str = "[::]",
    port: int = 50051,
    max_workers: int = 10,
    default_algorithm: str = "token_bucket",
) -> tuple[grpc.Server, int]:
    """Factory creating and binding a configured gRPC server."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    ratefortress_pb2_grpc.add_RateLimiterServicer_to_server(
        RateLimiterService(default_algorithm=default_algorithm), server
    )
    bound_port = server.add_insecure_port(f"{host}:{port}")
    return server, bound_port

