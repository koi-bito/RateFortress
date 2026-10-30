"""Configuration and identity resolution for RateFortress middleware."""

from dataclasses import dataclass
from typing import Any


@dataclass
class EndpointRule:
    """Rate limit configuration for an endpoint or route pattern."""

    limit: int = 100
    window_seconds: int = 60
    algorithm: str = "token_bucket"
    scope: str = "per_ip"  # "per_ip" or "per_user"


# Registered API keys with tier definitions and rate limit multipliers
API_KEYS: dict[str, dict[str, Any]] = {
    "key_free_abc": {
        "tier": "free",
        "limit_multiplier": 1,
        "description": "Standard free tier account",
    },
    "key_paid_xyz": {
        "tier": "paid",
        "limit_multiplier": 10,
        "description": "Premium paid tier account (10x quota)",
    },
    "key_enterprise_999": {
        "tier": "enterprise",
        "limit_multiplier": 50,
        "description": "Enterprise tier account (50x quota)",
    },
}

# Default route-based rate limit rules
DEFAULT_ROUTE_RULES: dict[str, EndpointRule] = {
    "default": EndpointRule(limit=100, window_seconds=60, algorithm="token_bucket"),
    "/": EndpointRule(limit=200, window_seconds=60, algorithm="token_bucket"),
    "/api/test": EndpointRule(limit=10, window_seconds=60, algorithm="token_bucket"),
    "/api/expensive-endpoint": EndpointRule(
        limit=5, window_seconds=60, algorithm="sliding_window_log"
    ),
    "/compare": EndpointRule(
        limit=30, window_seconds=60, algorithm="sliding_window_counter"
    ),
    "/metrics": EndpointRule(
        limit=60, window_seconds=60, algorithm="fixed_window"
    ),
}
