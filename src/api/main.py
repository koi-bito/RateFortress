"""RateFortress FastAPI Application Gateway."""

import os

import fakeredis.aioredis as fake_aio
from fastapi import FastAPI
from starlette.responses import Response

from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.monitoring.metrics import get_metrics_payload
from src.monitoring.tracing import setup_tracing
from src.storage.redis_client import get_redis_client, get_shared_fake_server


def create_app(backend: str | None = None) -> FastAPI:
    """Application factory supporting configurable rate limiting backends."""
    active_backend = backend or os.getenv("RATEFORTRESS_BACKEND", "memory").lower()

    application = FastAPI(
        title="RateFortress",
        version="0.1.0",
        description="High-performance distributed rate limiter engine and API gateway.",
    )

    # Initialize OpenTelemetry distributed tracing
    setup_tracing(application)

    redis_sync = None
    redis_async = None

    if active_backend == "redis_sync":
        redis_sync = get_redis_client()
    elif active_backend == "redis_async":
        server = get_shared_fake_server()
        redis_async = fake_aio.FakeRedis(server=server, db=0, decode_responses=True)

    # Attach production rate limiting middleware
    application.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_sync,
        async_redis_client=redis_async,
    )

    @application.get("/")
    def root():
        """Service health and root metadata."""
        return {"status": "ok", "service": "RateFortress", "version": "0.1.0"}

    @application.get("/health")
    def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    @application.get("/metrics")
    def metrics():
        """Prometheus scrape endpoint exposing gateway telemetry."""
        payload, content_type = get_metrics_payload()
        return Response(content=payload, media_type=content_type)

    @application.get("/api/test")
    def test_endpoint():
        """Standard test endpoint with default rate limits."""
        return {"message": "This endpoint is protected by RateFortress."}

    @application.get("/api/expensive-endpoint")
    def expensive_endpoint():
        """Simulated resource-heavy endpoint with strict sliding window log limits."""
        return {
            "message": "Expensive computation or database query completed successfully."
        }

    return application


app = create_app()
