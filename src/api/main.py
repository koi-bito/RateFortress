"""RateFortress FastAPI Application Gateway."""

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import fakeredis.aioredis as fake_aio
import redis.asyncio as aioredis
from fastapi import FastAPI
from starlette.responses import HTMLResponse, JSONResponse, Response

from src.api.admin import get_admin_key_manager
from src.api.admin import router as admin_router
from src.api.compare import router as compare_router
from src.middleware.priority_queue import PriorityRequestQueue
from src.middleware.rate_limit_middleware import RateLimitMiddleware
from src.monitoring.metrics import get_metrics_payload
from src.monitoring.tracing import setup_tracing
from src.storage.redis_client import get_redis_client, get_shared_fake_server

logger = logging.getLogger("ratefortress.api")


def create_app(
    backend: str | None = None,
    global_ip_limit: int | None = None,
    global_ip_window: int | None = None,
) -> FastAPI:
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
        # Startup: verify ADMIN_SECRET_KEY configuration
        admin_key = os.getenv("ADMIN_SECRET_KEY")
        if not admin_key or admin_key == "rf_admin_secret_master_key_2026":
            logger.error(
                "CRITICAL: ADMIN_SECRET_KEY is not set or using the default key. "
                "Admin API routes will return 503 Service Unavailable."
            )

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

        # Startup: subscribe to key invalidations across workers
        key_mgr = get_admin_key_manager()
        invalidation_sub = key_mgr.start_invalidation_listener()

        # Startup: register signal handlers for graceful shutdown (Day 143)
        def _handle_shutdown_signal(sig, frame):
            logger.info("Termination signal %s received. Initiating graceful shutdown...", sig)
            app.state.is_shutting_down = True
            middleware = getattr(app.state, "rate_limit_middleware", None)
            if middleware:
                middleware.is_shutting_down = True

        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is not None:
                try:
                    signal.signal(sig, _handle_shutdown_signal)
                except (ValueError, AttributeError, OSError):
                    pass

        yield

        # Shutdown: mark shutting down and drain in-flight requests (Day 143)
        app.state.is_shutting_down = True
        middleware = getattr(app.state, "rate_limit_middleware", None)
        if middleware:
            middleware.is_shutting_down = True
            try:
                grace_period = float(os.getenv("RATEFORTRESS_SHUTDOWN_GRACE_PERIOD", "5.0"))
                await middleware.drain_in_flight(timeout=grace_period)
            except Exception as exc:
                logger.debug("Error during graceful shutdown drain: %s", exc)

        # Shutdown: stop key invalidation subscriber
        if invalidation_sub is not None and hasattr(invalidation_sub, "stop"):
            try:
                invalidation_sub.stop()
            except Exception as exc:
                logger.debug("Error stopping invalidation subscriber: %s", exc)

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
    application.state.is_shutting_down = False

    # Initialize OpenTelemetry distributed tracing
    setup_tracing(application)

    # Shared persistent API key manager
    key_manager = get_admin_key_manager()

    # Attach production rate limiting middleware
    priority_queue = PriorityRequestQueue()
    application.state.priority_queue = priority_queue
    application.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_sync,
        async_redis_client=redis_async,
        key_manager=key_manager,
        priority_queue=priority_queue,
        global_ip_limit=global_ip_limit,
        global_ip_window=global_ip_window,
    )

    @application.get("/")
    def root():
        """Service health and root metadata."""
        return {"status": "ok", "service": "RateFortress", "version": "0.1.0"}

    @application.get("/health")
    def health():
        """Liveness check endpoint."""
        return {"status": "healthy"}

    @application.get("/health/ready")
    async def readiness():
        """Day 142 Readiness check: verifies backend connectivity and service availability."""
        if getattr(application.state, "is_shutting_down", False):
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "reason": "shutting_down",
                    "detail": "Instance is in the process of shutting down.",
                },
            )

        if active_backend == "memory":
            return {"status": "ready", "backend": "memory"}

        if active_backend == "redis_async":
            if redis_async is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "backend": "redis_async", "error": "Redis client uninitialized"},
                )
            try:
                await redis_async.ping()
                return {"status": "ready", "backend": "redis_async"}
            except Exception as exc:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "backend": "redis_async", "error": str(exc)},
                )

        if active_backend == "redis_sync":
            if redis_sync is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "backend": "redis_sync", "error": "Redis client uninitialized"},
                )
            try:
                redis_sync.ping()
                return {"status": "ready", "backend": "redis_sync"}
            except Exception as exc:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "backend": "redis_sync", "error": str(exc)},
                )

        return {"status": "ready", "backend": active_backend}

    @application.get("/metrics")
    def metrics():
        """Prometheus scrape endpoint exposing gateway telemetry."""
        payload, content_type = get_metrics_payload()
        return Response(content=payload, media_type=content_type)

    @application.get("/api/slow-request")
    async def slow_request(delay: float = 0.5):
        """Day 143 Test endpoint: artificial delay to verify in-flight request completion during shutdown."""
        await asyncio.sleep(delay)
        return {"status": "completed", "delayed_seconds": delay}

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
        html_path = Path(__file__).resolve().parents[2] / "templates" / "admin.html"
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>RateFortress Admin Dashboard</h1><p>Template file not found.</p>"
        )

    return application


app = create_app()
