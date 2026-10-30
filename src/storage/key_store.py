"""Persistent Key Store for RateFortress API Keys (Day 112).

Provides abstract and concrete storage layers for API key persistence across server restarts,
supporting Redis hashes/sets and an in-memory fallback.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from src.storage.redis_client import get_redis_client

logger = logging.getLogger("ratefortress.storage.key_store")


class KeyStore(ABC):
    """Abstract interface for API key metadata persistence."""

    @abstractmethod
    def get(self, key_id: str) -> dict[str, Any] | None:
        """Retrieves key metadata by key ID."""

    @abstractmethod
    def set(self, key_id: str, data: dict[str, Any]) -> None:
        """Stores or updates key metadata."""

    @abstractmethod
    def delete(self, key_id: str) -> bool:
        """Deletes key metadata from the store."""

    @abstractmethod
    def list_all(self) -> list[dict[str, Any]]:
        """Lists all stored key metadata records."""

    @abstractmethod
    def exists(self, key_id: str) -> bool:
        """Checks if a key exists in the store."""


class MemoryKeyStore(KeyStore):
    """Thread-safe in-memory key store for local development and unit tests."""

    def __init__(self, initial_data: dict[str, dict[str, Any]] | None = None):
        self._store: dict[str, dict[str, Any]] = {}
        if initial_data:
            for k, val in initial_data.items():
                self._store[k] = dict(val)

    def get(self, key_id: str) -> dict[str, Any] | None:
        val = self._store.get(key_id)
        return dict(val) if val is not None else None

    def set(self, key_id: str, data: dict[str, Any]) -> None:
        self._store[key_id] = dict(data)

    def delete(self, key_id: str) -> bool:
        return self._store.pop(key_id, None) is not None

    def list_all(self) -> list[dict[str, Any]]:
        return [dict(v) for v in self._store.values()]

    def exists(self, key_id: str) -> bool:
        return key_id in self._store


class RedisKeyStore(KeyStore):
    """Production Redis-backed key store storing metadata in hashes with an active index set."""

    KEY_PREFIX = "rf:keys:meta:"
    SET_NAME = "rf:keys:active_index"

    def __init__(self, redis_client: Any):
        self.redis = redis_client

    def _format_key(self, key_id: str) -> str:
        return f"{self.KEY_PREFIX}{key_id}"

    def get(self, key_id: str) -> dict[str, Any] | None:
        raw = self.redis.get(self._format_key(key_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to decode key metadata for %s: %s", key_id, exc)
            return None

    def set(self, key_id: str, data: dict[str, Any]) -> None:
        serialized = json.dumps(data)
        self.redis.set(self._format_key(key_id), serialized)
        self.redis.sadd(self.SET_NAME, key_id)

    def delete(self, key_id: str) -> bool:
        deleted = self.redis.delete(self._format_key(key_id))
        self.redis.srem(self.SET_NAME, key_id)
        return bool(deleted)

    def list_all(self) -> list[dict[str, Any]]:
        key_ids = self.redis.smembers(self.SET_NAME)
        if not key_ids:
            return []

        results: list[dict[str, Any]] = []
        for kid in sorted(key_ids):
            # kid might be bytes if decode_responses=False
            kid_str = kid.decode("utf-8") if isinstance(kid, bytes) else str(kid)
            meta = self.get(kid_str)
            if meta:
                results.append(meta)
        return results

    def exists(self, key_id: str) -> bool:
        return bool(self.redis.sismember(self.SET_NAME, key_id))


_global_key_store: KeyStore | None = None


def get_key_store(backend: str | None = None, redis_client: Any | None = None) -> KeyStore:
    """Returns the singleton KeyStore instance."""
    global _global_key_store
    if _global_key_store is not None and backend is None:
        return _global_key_store

    if backend == "memory":
        _global_key_store = MemoryKeyStore()
        return _global_key_store

    # Try redis client if provided or discoverable
    client = redis_client
    if client is None:
        try:
            client = get_redis_client(fallback_to_fake=True)
        except Exception as exc:
            logger.warning("Redis client unavailable for KeyStore (%s), using MemoryKeyStore", exc)
            _global_key_store = MemoryKeyStore()
            return _global_key_store

    _global_key_store = RedisKeyStore(client)
    return _global_key_store


def reset_key_store():
    """Resets global key store singleton (for test isolation)."""
    global _global_key_store
    _global_key_store = None
