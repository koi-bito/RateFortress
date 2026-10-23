"""Redis connection manager and storage backend utility for RateFortress.

Provides unified access to Redis connections, with support for connection pooling,
database indexing, and an optional in-process fallback (using fakeredis) for local
testing environments where Docker or a standalone Redis server is temporarily unavailable.
"""

import logging
import os
from typing import Any

import redis

logger = logging.getLogger("ratefortress.storage.redis")

# Shared in-process fake server instance for deterministic multi-client testing
_shared_fake_server = None


def get_shared_fake_server():
    """Returns a shared fakeredis FakeServer singleton for cross-instance simulation."""
    global _shared_fake_server
    if _shared_fake_server is None:
        try:
            import fakeredis

            _shared_fake_server = fakeredis.FakeServer()
        except ImportError:
            _shared_fake_server = None
    return _shared_fake_server


def get_redis_client(
    host: str | None = None,
    port: int | None = None,
    db: int = 0,
    password: str | None = None,
    decode_responses: bool = True,
    fallback_to_fake: bool = True,
) -> Any:
    """Creates and returns a Redis client.

    If a real Redis instance is reachable at the target host/port, returns a standard
    `redis.Redis` instance. If unreachable and `fallback_to_fake=True`, returns a
    `fakeredis.FakeRedis` client connected to a shared simulated server for seamless local testing.
    """
    redis_host = host or os.getenv("REDIS_HOST", "localhost")
    redis_port = port or int(os.getenv("REDIS_PORT", "6379"))
    redis_password = password or os.getenv("REDIS_PASSWORD", None)

    # Fast path if explicitly set or test mode
    if os.getenv("USE_FAKE_REDIS", "").lower() in ("1", "true", "yes"):
        import fakeredis

        server = get_shared_fake_server()
        return fakeredis.FakeRedis(
            server=server, db=db, decode_responses=decode_responses
        )

    try:
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=db,
            password=redis_password,
            decode_responses=decode_responses,
            socket_timeout=0.5,
            socket_connect_timeout=0.1,
        )
        # Verify connection
        client.ping()
        logger.info(
            f"Connected to live Redis server at {redis_host}:{redis_port} (db={db})"
        )
        return client
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        if fallback_to_fake:
            try:
                import fakeredis

                server = get_shared_fake_server()
                fake_client = fakeredis.FakeRedis(
                    server=server,
                    db=db,
                    decode_responses=decode_responses,
                )
                logger.warning(
                    f"Live Redis at {redis_host}:{redis_port} unavailable ({exc}). "
                    "Falling back to shared in-process FakeRedis."
                )
                return fake_client
            except ImportError:
                pass
        raise ConnectionError(
            f"Could not connect to Redis at {redis_host}:{redis_port}. "
            "Ensure Redis is running (e.g., via Docker: docker run -d -p 6379:6379 redis)."
        ) from exc
