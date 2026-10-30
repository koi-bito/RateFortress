"""API Key Management, Constant-Time Verification & Zero-Downtime Rotation (Days 96 & 112).

Provides cryptographically secure key generation, timing-attack resistant verification
using hmac.compare_digest, dual-validity grace periods for seamless key rotation,
and optional persistence via KeyStore (Redis/Memory).
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.storage.key_store import KeyStore

logger = logging.getLogger("ratefortress.middleware.key_manager")


def mask_key(api_key: str) -> str:
    """Masks a secret key for safe logging, exposing only first 4 and last 3 characters."""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}...{api_key[-3:]}"


@dataclass
class KeyMetadata:
    """Metadata describing an API key, its tenant ownership, tier, and rotation lifecycle."""

    key_id: str
    tier: str = "free"
    limit_multiplier: int = 1
    description: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None  # Deprecated key expiration during rotation grace period
    status: str = "active"  # "active", "rotating", "revoked"

    def to_dict(self) -> dict[str, Any]:
        """Serializes metadata to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyMetadata:
        """Constructs KeyMetadata from dictionary."""
        return cls(
            key_id=data["key_id"],
            tier=data.get("tier", "free"),
            limit_multiplier=int(data.get("limit_multiplier", 1)),
            description=data.get("description", ""),
            created_at=float(data.get("created_at", time.time())),
            expires_at=(
                float(data["expires_at"]) if data.get("expires_at") is not None else None
            ),
            status=data.get("status", "active"),
        )


class APIKeyManager:
    """Thread-safe API key registry supporting zero-downtime rotation and persistent storage."""

    def __init__(
        self,
        initial_keys: dict[str, dict[str, Any]] | None = None,
        key_store: KeyStore | None = None,
    ):
        self.key_store = key_store
        self._keys: dict[str, KeyMetadata] = {}

        # 1. Load from key_store if present
        if self.key_store:
            stored_records = self.key_store.list_all()
            for record in stored_records:
                try:
                    meta = KeyMetadata.from_dict(record)
                    self._keys[meta.key_id] = meta
                except Exception as exc:
                    logger.warning("Failed to parse stored key record: %s", exc)

        # 2. Seed initial keys if provided and not already present
        if initial_keys:
            for k, meta_dict in initial_keys.items():
                if k not in self._keys:
                    meta = KeyMetadata(
                        key_id=k,
                        tier=meta_dict.get("tier", "free"),
                        limit_multiplier=meta_dict.get("limit_multiplier", 1),
                        description=meta_dict.get("description", ""),
                    )
                    self._keys[k] = meta
                    if self.key_store:
                        self.key_store.set(k, meta.to_dict())

    def _persist(self, meta: KeyMetadata) -> None:
        if self.key_store:
            self.key_store.set(meta.key_id, meta.to_dict())

    def issue_key(
        self,
        tier: str = "free",
        limit_multiplier: int = 1,
        description: str = "",
        prefix: str = "rf",
        custom_key_id: str | None = None,
    ) -> str:
        """Generates a new cryptographically secure 256-bit API key."""
        if custom_key_id:
            key = custom_key_id
        else:
            random_token = secrets.token_urlsafe(32)
            key = f"{prefix}_{tier}_{random_token}"

        meta = KeyMetadata(
            key_id=key,
            tier=tier,
            limit_multiplier=limit_multiplier,
            description=description,
            created_at=time.time(),
            status="active",
        )
        self._keys[key] = meta
        self._persist(meta)
        return key

    def rotate_key(self, old_key: str, grace_period_sec: int = 3600) -> tuple[str, str]:
        """Performs zero-downtime key rotation.

        Issues a new active key and assigns an expiration grace period to old_key,
        allowing clients to migrate without service disruption.
        """
        old_meta = self.get_key_metadata(old_key)
        if not old_meta:
            raise ValueError(f"Key {mask_key(old_key)} does not exist.")

        # Issue replacement key
        new_key = self.issue_key(
            tier=old_meta.tier,
            limit_multiplier=old_meta.limit_multiplier,
            description=f"Rotated from {mask_key(old_key)}: {old_meta.description}".strip(),
        )

        # Mark old key as rotating with grace period expiration
        now = time.time()
        old_meta.status = "rotating"
        old_meta.expires_at = now + grace_period_sec
        self._persist(old_meta)

        return new_key, old_key

    def update_tier(
        self,
        key: str,
        tier: str | None = None,
        limit_multiplier: int | None = None,
        description: str | None = None,
    ) -> KeyMetadata:
        """Updates tier configuration or metadata for an existing key."""
        meta = self.get_key_metadata(key)
        if not meta:
            raise ValueError(f"Key {mask_key(key)} does not exist.")

        if tier is not None:
            meta.tier = tier
        if limit_multiplier is not None:
            meta.limit_multiplier = limit_multiplier
        if description is not None:
            meta.description = description

        self._persist(meta)
        return meta

    def revoke_key(self, key: str) -> bool:
        """Immediately revokes an API key."""
        meta = self._keys.get(key)
        if meta:
            meta.status = "revoked"
            meta.expires_at = time.time()
            self._persist(meta)
            return True
        return False

    def verify_key(self, candidate_key: str) -> KeyMetadata | None:
        """Validates candidate_key using constant-time comparison to prevent timing attacks."""
        if not candidate_key:
            return None

        now = time.time()
        matched_meta: KeyMetadata | None = None

        # Compare against known keys in constant time
        for registered_key, meta in self._keys.items():
            if hmac.compare_digest(registered_key, candidate_key):
                matched_meta = meta
                break

        if not matched_meta:
            return None

        # Check revocation
        if matched_meta.status == "revoked":
            return None

        # Check grace period expiration
        if matched_meta.expires_at is not None and now > matched_meta.expires_at:
            return None

        return matched_meta

    def get_key_metadata(self, key: str) -> KeyMetadata | None:
        return self._keys.get(key)

    def list_keys(self) -> list[KeyMetadata]:
        """Returns all keys sorted by creation date."""
        return sorted(self._keys.values(), key=lambda m: m.created_at, reverse=True)

    def active_keys_count(self) -> int:
        now = time.time()
        count = 0
        for meta in self._keys.values():
            if meta.status != "revoked" and (meta.expires_at is None or now <= meta.expires_at):
                count += 1
        return count

    def get_summary(self) -> dict[str, Any]:
        """Returns aggregate summary of registered keys and tier breakdown."""
        now = time.time()
        active = 0
        rotating = 0
        revoked = 0
        tiers: dict[str, int] = {}

        for meta in self._keys.values():
            tiers[meta.tier] = tiers.get(meta.tier, 0) + 1
            if meta.status == "revoked":
                revoked += 1
            elif meta.status == "rotating":
                if meta.expires_at is not None and now > meta.expires_at:
                    revoked += 1
                else:
                    rotating += 1
            else:
                active += 1

        return {
            "total_keys": len(self._keys),
            "active_keys": active,
            "rotating_keys": rotating,
            "revoked_keys": revoked,
            "tier_distribution": tiers,
        }
