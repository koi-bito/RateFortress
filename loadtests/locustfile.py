"""Locust load testing scenario file for RateFortress gateway.

Simulates realistic multi-tenant traffic across various endpoints, pricing tiers,
and rate-limiting quotas to evaluate latency, throughput, and error rates under load.
"""

import random

from locust import HttpUser, between, task


class RateFortressUser(HttpUser):
    """Simulated client hitting RateFortress endpoints under variable load."""

    # Inter-request think time between 100ms and 500ms
    wait_time = between(0.1, 0.5)

    def on_start(self):
        """Randomly assign an API key tier or anonymous identity to each simulated user."""
        tiers = [
            ("key_free_abc", "free"),
            ("key_free_abc", "free"),
            ("key_paid_xyz", "paid"),
            ("key_enterprise_999", "enterprise"),
            (None, "anonymous"),
        ]
        self.api_key, self.tier_name = random.choice(tiers)
        self.headers = {"X-API-Key": self.api_key} if self.api_key else {}

    @task(10)
    def hit_test_endpoint(self):
        """Primary test endpoint protected by token bucket rate limiter."""
        with self.client.get(
            "/api/test",
            headers=self.headers,
            catch_response=True,
            name="/api/test",
        ) as response:
            # Both 200 OK and 429 Too Many Requests are expected valid outcomes
            if response.status_code in (200, 429):
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

    @task(3)
    def hit_expensive_endpoint(self):
        """Resource-heavy endpoint protected by sliding window log."""
        with self.client.get(
            "/api/expensive-endpoint",
            headers=self.headers,
            catch_response=True,
            name="/api/expensive-endpoint",
        ) as response:
            if response.status_code in (200, 429):
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

    @task(1)
    def hit_health_check(self):
        """Health check endpoint."""
        with self.client.get(
            "/health",
            catch_response=True,
            name="/health",
        ) as response:
            if response.status_code in (200, 429):
                response.success()
            else:
                response.failure(f"Health check failed with {response.status_code}")
