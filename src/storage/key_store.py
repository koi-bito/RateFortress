"""Persistent Key Store for RateFortress API Keys (Day 112)."""

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
        pass

    @abstractmethod
    def set(self, key_id: str, data: dict[str, Any]) -> None:
        pass

    @abstractmethod
    def delete(self, key_id: str) -> bool:
        pass

    @abstractmethod
    def list_all(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def exists(self, key_id: str) -> bool:
        pass

    def publish_invalidation(self, message: str) -> None:
        pass

    def subscribe_invalidation(self, callback: Any) -> Any:
        return None


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
    """Redis-backed key store storing metadata in hashes with an active index set."""

    KEY_PREFIX = "rf:keys:meta:"
    SET_NAME = "rf:keys:active_index"
    INVALIDATION_CHANNEL = "ratefortress:key_invalidation"

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

        sorted_ids = [
            kid.decode("utf-8") if isinstance(kid, bytes) else str(kid)
            for kid in sorted(key_ids)
        ]
        formatted_keys = [self._format_key(kid) for kid in sorted_ids]
        raw_values = self.redis.mget(*formatted_keys)

        results: list[dict[str, Any]] = []
        for raw in raw_values:
            if not raw:
                continue
            try:
                results.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to decode key metadata from mget: %s", exc)
        return results

    def exists(self, key_id: str) -> bool:
        return bool(self.redis.sismember(self.SET_NAME, key_id))

    def publish_invalidation(self, message: str) -> None:
        try:
            self.redis.publish(self.INVALIDATION_CHANNEL, message)
        except Exception as exc:
            logger.warning("Failed to publish key invalidation message: %s", exc)

    def subscribe_invalidation(self, callback: Any) -> Any:
        try:
            pubsub = self.redis.pubsub()

            def _handler(msg: dict[str, Any]) -> None:
                data = msg.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                if isinstance(data, str):
                    callback(data)

            pubsub.subscribe(**{self.INVALIDATION_CHANNEL: _handler})
            return pubsub.run_in_thread(daemon=True)
        except Exception as exc:
            logger.warning("Failed to subscribe to key invalidations: %s", exc)
            return None


_global_key_store: KeyStore | None = None


def get_key_store(backend: str | None = None, redis_client: Any | None = None) -> KeyStore:
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
    global _global_key_store
    _global_key_store = None

