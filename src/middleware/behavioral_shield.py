"""Behavioral Anomaly & Bot Detection Shield (Day 104).

Analyzes inter-arrival request timing variance to distinguish between programmatic
script automation (near-zero jitter) and genuine human traffic. Dynamically scales
risk scores to downgrade suspicious actors to restricted tiers without hard-blocking.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque


class BehavioralShield:
    """Tracks inter-arrival timing jitter and computes composite behavioral risk scores."""

    def __init__(
        self,
        history_window: int = 10,
        regularity_threshold: float = 0.08,  # CV < 8% indicates programmatic regularity
        risk_threshold_suspicious: int = 50,
        risk_threshold_bot: int = 80,
    ):
        self.history_window = history_window
        self.regularity_threshold = regularity_threshold
        self.risk_threshold_suspicious = risk_threshold_suspicious
        self.risk_threshold_bot = risk_threshold_bot
        # Recent timestamps per client_id
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.history_window))
        # Account registration / first-seen epoch
        self._first_seen: dict[str, float] = defaultdict(time.time)

    def record_request(self, client_id: str, timestamp: float | None = None) -> float:
        """Records request arrival timestamp and returns coefficient of variation (CV)."""
        now = timestamp if timestamp is not None else time.time()
        history = self._history[client_id]
        history.append(now)

        if len(history) < 4:
            return 1.0  # Insufficient data, assume neutral/human variance

        # Calculate inter-arrival deltas
        deltas = [history[i] - history[i - 1] for i in range(1, len(history))]
        mean_delta = sum(deltas) / len(deltas)

        if mean_delta <= 0:
            return 0.0

        variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
        std_dev = math.sqrt(variance)
        cv = std_dev / mean_delta  # Coefficient of Variation
        return cv

    def calculate_risk_score(self, client_id: str, timestamp: float | None = None) -> tuple[int, str]:
        """Evaluates composite risk score (0-100) and returns (score, classification).

        Classifications:
        - "normal": Score < 50
        - "suspicious": 50 <= Score < 80 (downgrades quota multiplier to 0.2x)
        - "bot": Score >= 80 (downgrades quota multiplier to 0.1x)
        """
        now = timestamp if timestamp is not None else time.time()
        cv = self.record_request(client_id, now)
        history = self._history[client_id]

        score = 0

        # Signal 1: Near-zero timing variance (rigid script pacing)
        if len(history) >= 5:
            if cv < 0.02:
                score += 60  # Near-perfect script execution
            elif cv < self.regularity_threshold:
                score += 45  # Highly suspicious regular pacing
            elif cv < 0.15:
                score += 20  # Moderate regularity

        # Signal 2: Request velocity within first 5 seconds of first-seen
        first_seen = self._first_seen[client_id]
        account_age = max(0.001, now - first_seen)
        req_count = len(history)
        if account_age < 5.0 and req_count >= 8:
            score += 35  # Brand-new account immediate burst

        # Signal 3: Extremely high frequency (<10ms between requests)
        if len(history) >= 2:
            last_delta = history[-1] - history[-2]
            if last_delta < 0.01:
                score += 25

        score = min(100, score)

        if score >= self.risk_threshold_bot:
            classification = "bot"
        elif score >= self.risk_threshold_suspicious:
            classification = "suspicious"
        else:
            classification = "normal"

        return score, classification

    def get_tier_multiplier_adjustment(
        self, client_id: str, base_multiplier: int, timestamp: float | None = None
    ) -> int:
        """Applies dynamic penalty multiplier based on behavioral risk."""
        _, classification = self.calculate_risk_score(client_id, timestamp=timestamp)
        if classification == "bot":
            return max(1, int(base_multiplier * 0.1))
        elif classification == "suspicious":
            return max(1, int(base_multiplier * 0.2))
        return base_multiplier
