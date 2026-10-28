"""Asynchronous Redis connection manager for RateFortress.

Provides unified non-blocking access to Redis using redis.asyncio,
enabling FastAPI / ASGI event loops to perform rate-limiting checks and Lua script
executions without blocking worker threads during network I/O.
"""

import logging
import os
from typing import Any

import redis.asyncio as aioredis

from src.storage.redis_client import get_shared_fake_server

logger = logging.getLogger("ratefortress.storage.async_redis")


async def get_async_redis_client(
    host: str | None = None,
    port: int | None = None,
    db: int = 0,
    password: str | None = None,
    decode_responses: bool = True,
    fallback_to_fake: bool = True,
) -> Any:
    """Creates and returns an asynchronous Redis client.

    If a live Redis instance is reachable at host/port, returns `redis.asyncio.Redis`.
    If unreachable and `fallback_to_fake=True`, returns `fakeredis.aioredis.FakeRedis`
    bound to the shared fake server for local development and headless testing.
    """
    redis_host = host or os.getenv("REDIS_HOST", "localhost")
    redis_port = port or int(os.getenv("REDIS_PORT", "6379"))
    redis_password = password or os.getenv("REDIS_PASSWORD", None)

    # Fast path if explicitly flagged for tests or offline local simulation
    if os.getenv("USE_FAKE_REDIS", "").lower() in ("1", "true", "yes"):
        import fakeredis.aioredis as fake_aio

        server = get_shared_fake_server()
        return fake_aio.FakeRedis(
            server=server, db=db, decode_responses=decode_responses
        )

    try:
        client = aioredis.Redis(
            host=redis_host,
            port=redis_port,
            db=db,
            password=redis_password,
            decode_responses=decode_responses,
            socket_timeout=0.5,
            socket_connect_timeout=0.2,
        )
        await client.ping()
        logger.info(
            f"Connected to live async Redis at {redis_host}:{redis_port} (db={db})"
        )
        return client
    except Exception as exc:
        if fallback_to_fake:
            try:
                import fakeredis.aioredis as fake_aio

                server = get_shared_fake_server()
                fake_client = fake_aio.FakeRedis(
                    server=server,
                    db=db,
                    decode_responses=decode_responses,
                )
                logger.warning(
                    f"Live async Redis at {redis_host}:{redis_port} unavailable ({exc}). "
                    "Falling back to shared in-process FakeRedis (asyncio)."
                )
                return fake_client
            except ImportError:
                pass
        raise ConnectionError(
            f"Could not connect to async Redis at {redis_host}:{redis_port}."
        ) from exc
