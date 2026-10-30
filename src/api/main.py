"""RateFortress FastAPI Application Gateway."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import fakeredis.aioredis as fake_aio
import redis.asyncio as aioredis
from fastapi import FastAPI
from starlette.responses import HTMLResponse, Response

from src.api.admin import get_admin_key_manager
from src.api.admin import router as admin_router
from src.api.compare import router as compare_router
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.monitoring.metrics import get_metrics_payload
from src.monitoring.tracing import setup_tracing
from src.storage.redis_client import get_redis_client, get_shared_fake_server

logger = logging.getLogger("ratefortress.api")


def create_app(backend: str | None = None) -> FastAPI:
    """Application factory supporting configurable rate limiting backends."""
    active_backend = backend or os.getenv("RATEFORTRESS_BACKEND", "memory").lower()

    redis_sync = None
    redis_async = None

    if active_backend == "redis_sync":
        redis_sync = get_redis_client()
    elif active_backend == "redis_async":
        use_fake = os.getenv("USE_FAKE_REDIS", "").lower() in ("1", "true", "yes")
        if use_fake:
            server = get_shared_fake_server()
            redis_async = fake_aio.FakeRedis(server=server, db=0, decode_responses=True)
        else:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_password = os.getenv("REDIS_PASSWORD", None)
            redis_async = aioredis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                db=0,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: verify ping if live Redis
        if redis_async is not None:
            is_fake = isinstance(redis_async, getattr(fake_aio, "FakeRedis", ()))
            if not is_fake:
                try:
                    await redis_async.ping()
                    logger.info("Connected to live async Redis in lifespan startup.")
                except Exception as exc:
                    logger.error("Could not connect to async Redis in lifespan startup: %s", exc)
                    raise
        yield
        # Shutdown: close redis connections
        if redis_async is not None:
            try:
                await redis_async.aclose()
            except OSError as exc:
                logger.debug("Error closing async Redis connection: %s", exc)
        if redis_sync is not None:
            try:
                redis_sync.close()
            except OSError as exc:
                logger.debug("Error closing sync Redis connection: %s", exc)

    application = FastAPI(
        title="RateFortress",
        version="0.1.0",
        description="High-performance distributed rate limiter engine and API gateway.",
        lifespan=lifespan,
    )

    # Initialize OpenTelemetry distributed tracing
    setup_tracing(application)

    # Shared persistent API key manager
    key_manager = get_admin_key_manager()

    # Attach production rate limiting middleware
    application.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_sync,
        async_redis_client=redis_async,
        key_manager=key_manager,
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

    # Mount Week 12 Algorithm Comparison Engine
    application.include_router(compare_router)

    # Mount Week 23 Multi-Tenant Admin API
    application.include_router(admin_router)

    @application.get("/admin", response_class=HTMLResponse)
    @application.get("/dashboard", response_class=HTMLResponse)
    def admin_dashboard():
        """Serves the RateFortress multi-tenant administrative dashboard UI."""
        html_path = Path("templates/admin.html")
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>RateFortress Admin Dashboard</h1><p>Template file not found.</p>"
        )

    return application


app = create_app()
