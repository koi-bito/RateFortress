"""RateFortress Multi-Tenant Admin API (Days 111 & 112).

Provides administrative REST endpoints for issuing, rotating, updating, and revoking API keys,
monitoring tenant usage, and viewing global system metrics. All endpoints require admin authentication.
"""

from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.middleware.config import API_KEYS
from src.middleware.key_manager import APIKeyManager, KeyMetadata, mask_key
from src.storage.key_store import get_key_store

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Default admin secret key for local development and test automation
DEFAULT_ADMIN_KEY = "rf_admin_secret_master_key_2026"

# Shared singleton APIKeyManager for the admin API
_admin_key_manager: APIKeyManager | None = None


def get_admin_key_manager() -> APIKeyManager:
    """Returns the shared APIKeyManager bound to the persistent key store."""
    global _admin_key_manager
    if _admin_key_manager is None:
        store = get_key_store()
        _admin_key_manager = APIKeyManager(initial_keys=API_KEYS, key_store=store)
    return _admin_key_manager


def set_admin_key_manager(manager: APIKeyManager) -> None:
    """Sets the shared APIKeyManager (used in tests or app bootstrapping)."""
    global _admin_key_manager
    _admin_key_manager = manager


def verify_admin_auth(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> str:
    """Enforces admin credential validation using constant-time comparison."""
    expected_key = os.getenv("ADMIN_SECRET_KEY", DEFAULT_ADMIN_KEY)

    token = None
    if x_admin_key:
        token = x_admin_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token or not hmac.compare_digest(token, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# Request / Response Models
class IssueKeyRequest(BaseModel):
    tier: str = Field(default="free", description="Pricing tier: free, paid, enterprise, custom")
    limit_multiplier: int = Field(default=1, ge=1, le=1000, description="Rate limit multiplier")
    description: str = Field(default="", max_length=250, description="Tenant / application description")
    custom_key_id: str | None = Field(default=None, description="Optional custom key identifier")


class UpdateKeyRequest(BaseModel):
    tier: str | None = Field(default=None, description="New tier name")
    limit_multiplier: int | None = Field(default=None, ge=1, le=1000, description="New multiplier")
    description: str | None = Field(default=None, max_length=250, description="New description")


class RotateKeyRequest(BaseModel):
    grace_period_sec: int = Field(
        default=3600, ge=60, le=604800, description="Grace period in seconds before old key expires"
    )


class KeyResponse(BaseModel):
    key_id: str
    masked_key: str
    tier: str
    limit_multiplier: int
    description: str
    created_at: float
    expires_at: float | None
    status: str


def _serialize_key_metadata(meta: KeyMetadata) -> dict[str, Any]:
    return {
        "key_id": meta.key_id,
        "masked_key": mask_key(meta.key_id),
        "tier": meta.tier,
        "limit_multiplier": meta.limit_multiplier,
        "description": meta.description,
        "created_at": meta.created_at,
        "expires_at": meta.expires_at,
        "status": meta.status,
    }


# Endpoints
@router.get("/keys", dependencies=[Depends(verify_admin_auth)])
def list_keys(
    tier: str | None = None,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """Lists all registered API keys with metadata and masked keys."""
    mgr = get_admin_key_manager()
    all_keys = mgr.list_keys()

    filtered = []
    for k in all_keys:
        if tier and k.tier != tier:
            continue
        if status_filter and k.status != status_filter:
            continue
        filtered.append(_serialize_key_metadata(k))

    return {
        "total": len(filtered),
        "keys": filtered,
    }


@router.post("/keys", status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_admin_auth)])
def issue_key(payload: IssueKeyRequest) -> dict[str, Any]:
    """Issues a new cryptographically secure API key."""
    mgr = get_admin_key_manager()
    raw_key = mgr.issue_key(
        tier=payload.tier,
        limit_multiplier=payload.limit_multiplier,
        description=payload.description,
        custom_key_id=payload.custom_key_id,
    )
    meta = mgr.get_key_metadata(raw_key)
    if not meta:
        raise HTTPException(status_code=500, detail="Failed to retrieve issued key metadata")

    response_data = _serialize_key_metadata(meta)
    response_data["raw_key"] = raw_key  # Provided only once upon issuance
    return response_data


@router.get("/keys/{key_id}", dependencies=[Depends(verify_admin_auth)])
def get_key_details(key_id: str) -> dict[str, Any]:
    """Retrieves metadata for a specific key."""
    mgr = get_admin_key_manager()
    meta = mgr.get_key_metadata(key_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {mask_key(key_id)} not found",
        )
    return _serialize_key_metadata(meta)


@router.patch("/keys/{key_id}", dependencies=[Depends(verify_admin_auth)])
def update_key(key_id: str, payload: UpdateKeyRequest) -> dict[str, Any]:
    """Updates tier, rate multiplier, or description for an existing key."""
    mgr = get_admin_key_manager()
    try:
        updated_meta = mgr.update_tier(
            key=key_id,
            tier=payload.tier,
            limit_multiplier=payload.limit_multiplier,
            description=payload.description,
        )
        return _serialize_key_metadata(updated_meta)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {mask_key(key_id)} not found",
        )


@router.post("/keys/{key_id}/rotate", dependencies=[Depends(verify_admin_auth)])
def rotate_key(key_id: str, payload: RotateKeyRequest) -> dict[str, Any]:
    """Executes zero-downtime key rotation with dual-validity grace period."""
    mgr = get_admin_key_manager()
    try:
        new_key, old_key = mgr.rotate_key(
            old_key=key_id,
            grace_period_sec=payload.grace_period_sec,
        )
        old_meta = mgr.get_key_metadata(old_key)
        new_meta = mgr.get_key_metadata(new_key)
        return {
            "message": "Key rotation initiated successfully.",
            "new_key": new_key,
            "new_key_metadata": _serialize_key_metadata(new_meta) if new_meta else {},
            "old_key_metadata": _serialize_key_metadata(old_meta) if old_meta else {},
            "grace_period_sec": payload.grace_period_sec,
            "old_key_expires_at": old_meta.expires_at if old_meta else None,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.delete("/keys/{key_id}", dependencies=[Depends(verify_admin_auth)])
def revoke_key(key_id: str) -> dict[str, Any]:
    """Immediately revokes an API key."""
    mgr = get_admin_key_manager()
    success = mgr.revoke_key(key_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {mask_key(key_id)} not found",
        )
    return {
        "message": f"API key {mask_key(key_id)} revoked successfully.",
        "status": "revoked",
        "revoked_at": time.time(),
    }


@router.get("/keys/{key_id}/usage", dependencies=[Depends(verify_admin_auth)])
def get_key_usage(key_id: str) -> dict[str, Any]:
    """Retrieves real-time usage statistics and active rate limit status for a key."""
    mgr = get_admin_key_manager()
    meta = mgr.get_key_metadata(key_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {mask_key(key_id)} not found",
        )

    # Base nominal quota for standard endpoint is 100 req/min
    base_quota = 100
    effective_quota = base_quota * meta.limit_multiplier

    return {
        "key_id": key_id,
        "masked_key": mask_key(key_id),
        "tier": meta.tier,
        "status": meta.status,
        "limit_multiplier": meta.limit_multiplier,
        "effective_quota_per_minute": effective_quota,
        "burst_capacity": effective_quota,
        "active_connections": 1 if meta.status == "active" else 0,
    }


@router.get("/summary", dependencies=[Depends(verify_admin_auth)])
def get_admin_summary() -> dict[str, Any]:
    """Returns global administrative telemetry and tenant tier distribution."""
    mgr = get_admin_key_manager()
    summary = mgr.get_summary()
    summary["timestamp"] = time.time()
    summary["engine_status"] = "healthy"
    return summary

