"""Seed Script for RateFortress Admin API Keys (Day 112).

Populates default demo keys and tier configs into the persistent KeyStore (Redis or in-memory).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.middleware.config import API_KEYS
from src.middleware.key_manager import APIKeyManager
from src.storage.key_store import get_key_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_admin_keys")


def seed_keys() -> int:
    """Seeds the initial API keys into the persistent KeyStore."""
    store = get_key_store()
    manager = APIKeyManager(initial_keys=API_KEYS, key_store=store)

    seeded_count = 0
    for key, data in API_KEYS.items():
        existing = manager.get_key_metadata(key)
        if not existing:
            manager.issue_key(
                tier=data.get("tier", "free"),
                limit_multiplier=data.get("limit_multiplier", 1),
                description=data.get("description", ""),
                custom_key_id=key,
            )
            seeded_count += 1
            logger.info("Seeded key: %s (tier=%s)", key, data.get("tier"))
        else:
            logger.info("Key %s already exists in store.", key)

    total_keys = len(manager.list_keys())
    logger.info("Seeding complete. Total keys in store: %d", total_keys)
    return total_keys


if __name__ == "__main__":
    seed_keys()
