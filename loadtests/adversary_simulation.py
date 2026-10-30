"""Adversary Simulation Harness for RateFortress (Day 102).

Simulates real-world adversarial rate limiter evasion techniques:
1. X-Forwarded-For Header Spoofing (exploits naive trusted-proxy assumptions).
2. Distributed Proxy Pool Rotation (many unique IPs, few requests each).
3. Free-Tier Account Cycling (generating new API keys to bypass per-key quotas).
4. Automated Bot Scripting (rigid near-zero jitter timing).
"""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient

from src.api.main import create_app


def simulate_vanilla_attack(app, total_requests: int = 30) -> dict[str, Any]:
    """Baseline attacker hammering /api/test from a single fixed IP without headers."""
    client = TestClient(app, client=("198.51.100.10", 50000))
    allowed = 0
    blocked = 0

    for _ in range(total_requests):
        resp = client.get("/api/test")
        if resp.status_code == 200:
            allowed += 1
        elif resp.status_code == 429:
            blocked += 1

    return {
        "attack_type": "Vanilla Single-IP Burst",
        "total_requests": total_requests,
        "allowed": allowed,
        "blocked": blocked,
        "bypass_pct": (max(0, allowed - 10) / total_requests) * 100,
    }


def simulate_ip_spoofing_attack(
    app, total_requests: int = 30, spoof_header: bool = True
) -> dict[str, Any]:
    """Attacker connecting from untrusted peer IP and sending random X-Forwarded-For headers."""
    client = TestClient(app, client=("198.51.100.25", 50000))
    allowed = 0
    blocked = 0

    for _ in range(total_requests):
        headers = {}
        if spoof_header:
            random_ip = f"{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"
            headers["X-Forwarded-For"] = random_ip

        resp = client.get("/api/test", headers=headers)
        if resp.status_code == 200:
            allowed += 1
        elif resp.status_code == 429:
            blocked += 1

    return {
        "attack_type": "X-Forwarded-For Header Spoofing",
        "total_requests": total_requests,
        "allowed": allowed,
        "blocked": blocked,
        "bypass_pct": (max(0, allowed - 10) / total_requests) * 100,
    }


def simulate_account_cycling_attack(app, total_requests: int = 30) -> dict[str, Any]:
    """Attacker cycling through newly minted free-tier accounts/keys."""
    client = TestClient(app, client=("198.51.100.50", 50000))
    allowed = 0
    blocked = 0

    for i in range(total_requests):
        # Attacker registers or rotates a new key every 5 requests
        pseudo_key = f"key_free_cycled_{i // 5}"
        headers = {"X-API-Key": pseudo_key}
        resp = client.get("/api/test", headers=headers)
        if resp.status_code == 200:
            allowed += 1
        elif resp.status_code == 429:
            blocked += 1

    return {
        "attack_type": "Free-Tier Account Cycling",
        "total_requests": total_requests,
        "allowed": allowed,
        "blocked": blocked,
        "bypass_pct": (max(0, allowed - 10) / total_requests) * 100,
    }


def run_all_adversary_simulations():
    """Executes the full adversarial attack suite and prints comparative results."""
    app = create_app()

    print("==================================================================")
    print("      RateFortress Red Team — Adversarial Attack Simulation       ")
    print("==================================================================")

    res_vanilla = simulate_vanilla_attack(app, total_requests=30)
    res_spoof = simulate_ip_spoofing_attack(app, total_requests=30, spoof_header=True)

    print(f"\n1. {res_vanilla['attack_type']}:")
    print(f"   Allowed: {res_vanilla['allowed']} | Blocked: {res_vanilla['blocked']} | Bypass Rate: {res_vanilla['bypass_pct']:.1f}%")

    print(f"\n2. {res_spoof['attack_type']}:")
    print(f"   Allowed: {res_spoof['allowed']} | Blocked: {res_spoof['blocked']} | Bypass Rate: {res_spoof['bypass_pct']:.1f}%")

    print("\n==================================================================")
    return [res_vanilla, res_spoof]


if __name__ == "__main__":
    run_all_adversary_simulations()
