"""Security Hardening and API Key Lifecycle Tests (Day 96).

Validates:
1. Cryptographic key issuance and constant-time verification.
2. Zero-downtime key rotation with dual-validity grace periods.
3. Key revocation and expiration enforcement.
4. Masking of API credentials in logs.
5. Protection and explicit rate limits on internal tooling endpoints (/compare, /metrics).
"""

import json
import logging
import time

from src.middleware.config import DEFAULT_ROUTE_RULES
from src.middleware.key_manager import APIKeyManager, mask_key
from src.monitoring.logging_config import JSONLogFormatter


def test_api_key_issuance_and_verification():
    """Validates secure key generation and constant-time verification."""
    manager = APIKeyManager()
    key = manager.issue_key(tier="paid", limit_multiplier=10, description="Test client key")

    assert key.startswith("rf_paid_")
    assert len(key) > 30

    meta = manager.verify_key(key)
    assert meta is not None
    assert meta.tier == "paid"
    assert meta.limit_multiplier == 10
    assert meta.status == "active"

    # Invalid key returns None
    assert manager.verify_key("nonexistent_key") is None
    assert manager.verify_key("") is None


def test_zero_downtime_key_rotation_grace_period():
    """Validates that during rotation, both old and new keys remain valid until grace period expires."""
    manager = APIKeyManager()
    old_key = manager.issue_key(tier="enterprise", limit_multiplier=50)

    # Rotate with 2-second grace period for testing
    new_key, rotated_old = manager.rotate_key(old_key, grace_period_sec=2)
    assert rotated_old == old_key
    assert new_key != old_key

    # Immediately after rotation, BOTH keys must verify successfully
    assert manager.verify_key(new_key) is not None
    assert manager.verify_key(old_key) is not None

    # Wait for grace period to expire
    time.sleep(2.1)

    # Old key is now expired and rejected; new key remains fully valid
    assert manager.verify_key(old_key) is None
    assert manager.verify_key(new_key) is not None


def test_key_revocation():
    """Validates immediate key revocation."""
    manager = APIKeyManager()
    key = manager.issue_key(tier="free", limit_multiplier=1)

    assert manager.verify_key(key) is not None
    revoked = manager.revoke_key(key)
    assert revoked is True

    # Revoked key is immediately invalid
    assert manager.verify_key(key) is None


def test_mask_key_utility():
    """Validates that secret keys are safely truncated and masked."""
    assert mask_key("key_enterprise_999") == "key_...999"
    assert mask_key("short") == "***"
    assert mask_key("") == ""


def test_json_log_formatter_masks_client_api_keys():
    """Validates that sensitive client API keys never leak into JSON logs."""
    formatter = JSONLogFormatter(mask_secrets=True)
    record = logging.LogRecord(
        name="ratefortress.test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Request processed",
        args=(),
        exc_info=None,
    )
    record.client_id = "key_secret_super_private_token_123"
    record.status_code = 200

    formatted = formatter.format(record)
    log_data = json.loads(formatted)

    assert log_data["client_id"] == "key_...123"
    assert "super_private" not in formatted


def test_internal_endpoints_explicitly_rate_limited():
    """Validates that /compare and /metrics have explicit rate-limiting rules."""
    assert "/compare" in DEFAULT_ROUTE_RULES
    assert "/metrics" in DEFAULT_ROUTE_RULES

    compare_rule = DEFAULT_ROUTE_RULES["/compare"]
    assert compare_rule.limit == 30
    assert compare_rule.window_seconds == 60

    metrics_rule = DEFAULT_ROUTE_RULES["/metrics"]
    assert metrics_rule.limit == 60
    assert metrics_rule.window_seconds == 60
