"""Storage backend package for RateFortress (In-Memory, Redis, etc.)."""

from src.storage.redis_client import get_redis_client, get_shared_fake_server

__all__ = ["get_redis_client", "get_shared_fake_server"]
