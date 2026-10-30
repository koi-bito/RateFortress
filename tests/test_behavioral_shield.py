"""Unit tests for the Behavioral Anomaly Shield (Day 104)."""

import random

from src.middleware.behavioral_shield import BehavioralShield


def test_rigid_script_timing_flagged_as_suspicious():
    """Validates that a script with near-zero timing variance triggers high risk score."""
    shield = BehavioralShield()
    client_id = "bot_script_client"

    # Simulate programmatic loop sending requests exactly every 0.050 seconds
    base_time = 1000.0
    for i in range(10):
        t = base_time + (i * 0.050)
        score, classification = shield.calculate_risk_score(client_id, timestamp=t)

    assert score >= 50
    assert classification in ("suspicious", "bot")


def test_human_jitter_traffic_classified_as_normal():
    """Validates that human traffic with natural timing variance retains normal classification."""
    shield = BehavioralShield()
    client_id = "human_client"

    base_time = 1000.0
    current_time = base_time

    # Simulate realistic human reading pauses and variable click intervals
    random.seed(42)
    for _ in range(10):
        jitter = random.uniform(0.200, 1.500)
        current_time += jitter
        score, classification = shield.calculate_risk_score(client_id, timestamp=current_time)

    # Human jitter should maintain low risk score
    assert score < 50
    assert classification == "normal"


def test_tier_multiplier_dynamic_downgrade():
    """Validates that high-risk actors receive penalized multipliers without hard drops."""
    shield = BehavioralShield()
    bot_id = "automated_crawler"

    # Rigid loop
    base_time = 1000.0
    for i in range(8):
        t = base_time + (i * 0.005)  # ultra-fast 5ms intervals
        shield.calculate_risk_score(bot_id, timestamp=t)

    # Base paid multiplier is 10
    adjusted = shield.get_tier_multiplier_adjustment(bot_id, base_multiplier=10, timestamp=1000.040)
    assert adjusted < 10
    assert adjusted in (1, 2)
