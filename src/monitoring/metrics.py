"""Prometheus Metrics Instrumentation for RateFortress (Week 10).

Provides standardized Prometheus metric primitives (Counters, Histograms, and Gauges)
for end-to-end request tracking, rate limiting evaluation overhead, and blocked
request monitoring across client pricing tiers and algorithms.
"""

import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# 1. Total Requests Counter (labeled by endpoint, status, algorithm, and pricing tier)
REQUEST_COUNT = Counter(
    "ratefortress_requests_total",
    "Total incoming HTTP requests processed by RateFortress",
    ["endpoint", "status", "algorithm", "tier"],
)

# 2. Blocked Requests Counter (specifically tracks throttled HTTP 429 actions)
BLOCKED_REQUESTS = Counter(
    "ratefortress_blocked_requests_total",
    "Total requests throttled or rejected due to rate limit quota exhaustion",
    ["endpoint", "tier", "algorithm"],
)

# 3. Request Latency Histogram (end-to-end HTTP request processing time)
REQUEST_LATENCY = Histogram(
    "ratefortress_request_latency_seconds",
    "End-to-end HTTP request duration in seconds",
    ["endpoint", "status"],
    buckets=[
        0.0005,
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
    ],
)

# 4. Rate Limiter Overhead Histogram (time spent purely executing rate limit checks)
LIMITER_OVERHEAD = Histogram(
    "ratefortress_limiter_overhead_seconds",
    "Time spent exclusively inside rate limit evaluation and storage I/O",
    ["algorithm", "tier"],
    buckets=[
        0.00005,
        0.0001,
        0.00025,
        0.0005,
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
    ],
)

# 5. Active In-Flight Requests Gauge
ACTIVE_REQUESTS = Gauge(
    "ratefortress_active_requests",
    "Current number of active concurrent requests in flight",
)


def get_metrics_payload() -> tuple[bytes, str]:
    """Generates the latest Prometheus-formatted metrics payload."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
