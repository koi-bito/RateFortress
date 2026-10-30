"""Algorithm Comparison Engine for RateFortress.

Runs synthetic traffic across all five pure-Python rate limiting algorithms
(Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket)
and generates empirical comparison reports covering allowed/blocked metrics, decision latency,
algorithmic tradeoffs, and fairness analysis across uniform and skewed traffic distributions.
"""

from __future__ import annotations

import logging
import time
import unittest.mock
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.algorithms.fixed_window import FixedWindowCounter
from src.algorithms.gcra import GCRA
from src.algorithms.leaky_bucket import LeakyBucket
from src.algorithms.sliding_window_counter import SlidingWindowCounter
from src.algorithms.sliding_window_log import SlidingWindowLog
from src.algorithms.token_bucket import TokenBucket

logger = logging.getLogger("ratefortress.compare")

# Path to template files
TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["comparison"])


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ScenarioConfig(BaseModel):
    """Configuration parameters defining the synthetic traffic scenario."""

    users: int = Field(..., description="Total synthetic users in the scenario")
    requests_per_user: int = Field(..., description="Number of requests sent per user")
    window_seconds: int = Field(
        ..., description="Rate limiting window duration in seconds"
    )
    limit: int = Field(..., description="Nominal allowed request limit per user")
    pattern: str = Field(
        ..., description="Traffic distribution pattern ('uniform' or 'skewed')"
    )
    total_requests: int = Field(
        ..., description="Total generated requests (users × requests_per_user)"
    )


class TradeoffData(BaseModel):
    """Qualitative algorithmic tradeoff characteristics."""

    accuracy: str
    memory: str
    performance: str
    fairness: str
    strength: str
    weakness: str
    ideal_scenario: str


class FairnessData(BaseModel):
    """Empirical fairness analysis comparing steady and bursty clients."""

    bursty_users_count: int
    steady_users_count: int
    bursty_users_allowed: int
    bursty_users_total: int
    bursty_users_allowed_pct: float
    steady_users_allowed: int
    steady_users_total: int
    steady_users_allowed_pct: float
    favors: str = Field(
        ..., description="Empirical bias: 'bursty', 'steady', or 'neutral'"
    )


class AlgorithmResult(BaseModel):
    """Evaluation metrics for an individual rate-limiting algorithm."""

    algorithm: str
    display_name: str
    allowed: int
    blocked: int
    allowed_pct: float
    blocked_pct: float
    avg_latency_ms: float
    tradeoffs: TradeoffData
    fairness: FairnessData


class ComparisonResponse(BaseModel):
    """Structured response from the /compare benchmark engine."""

    scenario: ScenarioConfig
    results: list[AlgorithmResult]


# ---------------------------------------------------------------------------
# Static Qualitative Tradeoff Knowledge Base (Mirrors docs/tradeoffs.md)
# ---------------------------------------------------------------------------

TRADEOFFS_CATALOG: dict[str, dict[str, str]] = {
    "fixed_window": {
        "accuracy": "Suffers from window boundary burst (up to 2x nominal limit allowed across boundary transitions).",
        "memory": "O(1) per user. Requires only a single counter integer and current epoch timestamp in memory/Redis.",
        "performance": "Fastest execution. Redis native INCR operates at ~43,300 req/s with sub-microsecond in-memory lookups.",
        "fairness": "Variable. Favors clients that align requests with window reset edges, producing unfair downstream bursts.",
        "strength": "Minimal computational and memory overhead across high scale.",
        "weakness": "Traffic spikes up to 200% quota at reset boundaries.",
        "ideal_scenario": "High-volume public APIs with coarse windows where memory economy is paramount and occasional boundary bursts are acceptable.",
    },
    "sliding_window_log": {
        "accuracy": "100% mathematically exact rolling window. Prevents any boundary burst or rate leakage.",
        "memory": "O(N) per user, where N is request count. Memory scales linearly with traffic, risking high Redis RAM costs.",
        "performance": "Lowest throughput. Trimming and querying sorted sets (ZSET) operates at ~5,850 req/s in Redis Lua.",
        "fairness": "Strictly uniform. Every request is evaluated against the continuous rolling window interval [now - W, now].",
        "strength": "Absolute precision with zero rate limit evasion.",
        "weakness": "High memory consumption under heavy traffic.",
        "ideal_scenario": "Security-critical endpoints (login, password reset, payment auth, OTP) where abuse prevention is vital and volume is moderate.",
    },
    "sliding_window_counter": {
        "accuracy": "Approximates sliding window using rolling weighted average between previous and current window (error < 0.05%).",
        "memory": "O(1) per user. Stores only two integer counters (current window and previous window).",
        "performance": "Very fast. Atomic Lua script executes at ~7,200 req/s with O(1) in-memory arithmetic.",
        "fairness": "Smooth and balanced. Eliminates fixed window boundary cliffs without storing individual timestamps.",
        "strength": "Production sweet spot balancing sliding accuracy with constant O(1) memory footprint.",
        "weakness": "Slight statistical approximation bias under extreme non-uniform traffic bursts within a window.",
        "ideal_scenario": "High-throughput general SaaS REST APIs (e.g. Cloudflare edge rate limiting) needing sliding window protection with fixed RAM budget.",
    },
    "token_bucket": {
        "accuracy": "Accurate sustained rate enforcement. Allows controlled burstiness up to capacity B while enforcing refill rate R.",
        "memory": "O(1) per user. Stores token balance float and last refill timestamp float.",
        "performance": "Very high. Refill calculation runs in O(1) time (~6,530 req/s in Redis Lua).",
        "fairness": "Favors bursty clients! Idle users accumulate tokens up to capacity and can send rapid bursts without drops.",
        "strength": "Supports natural client burstiness (e.g. web page load with 15 parallel assets) without blocking.",
        "weakness": "Bursts may shock downstream database connections or microservices if bucket capacity is configured too high.",
        "ideal_scenario": "Developer APIs and webhooks where clients naturally perform batch operations followed by idle intervals.",
    },
    "leaky_bucket": {
        "accuracy": "Strict traffic shaping. Enforces a smooth, constant outflow rate; drops all requests exceeding buffer capacity.",
        "memory": "O(1) per user with virtual leak math (or O(B) with physical request queue).",
        "performance": "Very high. Constant-time leak calculation (~6,310 req/s in Redis Lua).",
        "fairness": "Penalizes bursty clients! Bursts rapidly fill the queue and overflow into 429 drops, while steady clients pass 100%.",
        "strength": "Guarantees perfectly smooth downstream outflow rate and protects fragile services.",
        "weakness": "Zero burst tolerance; legitimately bursty clients suffer high rejection rates.",
        "ideal_scenario": "Ingestion gateways fronting fragile backend dependencies (legacy databases, payment gateways, heavy PDF workers) that cannot tolerate bursts.",
    },
    "gcra": {
        "accuracy": "Exact virtual cell scheduling. Uses Theoretical Arrival Time (TAT) to enforce limits with zero mathematical boundary drift.",
        "memory": "O(1) strictly minimal (~32 bytes per user in Redis, tracking a single float timestamp).",
        "performance": "Ultra high. In-memory ~3.3M req/s, Redis Lua ~6.7k req/s.",
        "fairness": "Similar to Token Bucket: permits controlled bursts up to burst tolerance tau, while steady clients pass cleanly.",
        "strength": "Production standard used by Stripe and Redis Cell. Elegant single-key state without float token decay math.",
        "weakness": "Non-trivial conceptual model compared to simple counters.",
        "ideal_scenario": "High-throughput cloud APIs, payment platforms, and multi-tenant SaaS where low memory overhead and burst support are both required.",
    },
}

ALGORITHMS_REGISTRY: list[tuple[str, str, Any]] = [
    (
        "fixed_window",
        "Fixed Window Counter",
        lambda l, w: FixedWindowCounter(limit=l, window_seconds=w),
    ),
    (
        "sliding_window_log",
        "Sliding Window Log",
        lambda l, w: SlidingWindowLog(limit=l, window_seconds=w),
    ),
    (
        "sliding_window_counter",
        "Sliding Window Counter",
        lambda l, w: SlidingWindowCounter(limit=l, window_seconds=w),
    ),
    (
        "token_bucket",
        "Token Bucket",
        lambda l, w: TokenBucket(capacity=l, refill_rate_per_sec=float(l) / float(w)),
    ),
    (
        "leaky_bucket",
        "Leaky Bucket",
        lambda l, w: LeakyBucket(capacity=l, leak_rate_per_sec=float(l) / float(w)),
    ),
    (
        "gcra",
        "GCRA (Cell Rate)",
        lambda l, w: GCRA(limit=l, period=float(w)),
    ),
]


# ---------------------------------------------------------------------------
# Synthetic Traffic Generation
# ---------------------------------------------------------------------------


class VirtualClock:
    """Controllable clock replacing time.time() during pure-Python simulation."""

    def __init__(self, start_time: float = 10000.0):
        self.current_time = start_time

    def __call__(self) -> float:
        return self.current_time


def generate_synthetic_traffic(
    users: int,
    requests_per_user: int,
    window_seconds: int,
    pattern: str = "uniform",
) -> tuple[list[tuple[str, float, bool]], int, int]:
    """Generates synthetic requests (user_id, timestamp_offset, is_bursty).

    Returns:
        tuple containing:
        - Sorted list of request tuples (user_id, timestamp_offset, is_bursty)
        - Count of bursty users
        - Count of steady users
    """
    requests: list[tuple[str, float, bool]] = []
    w = float(window_seconds)

    if pattern == "skewed":
        bursty_users_count = (
            max(1, round(users * 0.2)) if users > 1 else (1 if users == 1 else 0)
        )
        steady_users_count = max(0, users - bursty_users_count)
    else:
        bursty_users_count = 0
        steady_users_count = users

    # 1. Steady Users: requests evenly spaced across 5% to 95% of the window
    for u in range(steady_users_count):
        user_id = f"steady_usr_{u}"
        jitter = ((u * 17) % 100) / 1000.0 * (w * 0.05)
        for i in range(requests_per_user):
            fraction = (
                (i / max(1, requests_per_user - 1)) if requests_per_user > 1 else 0.5
            )
            t = (fraction * (w * 0.90)) + (w * 0.05) + jitter
            requests.append((user_id, t, False))

    # 2. Bursty Users: all requests tightly packed into initial 15% of the window
    for u in range(bursty_users_count):
        user_id = f"bursty_usr_{u}"
        jitter = ((u * 13) % 100) / 1000.0 * (w * 0.02)
        for i in range(requests_per_user):
            fraction = (
                (i / max(1, requests_per_user - 1)) if requests_per_user > 1 else 0.05
            )
            t = (fraction * (w * 0.15)) + (w * 0.05) + jitter
            requests.append((user_id, t, True))

    # Chronologically sort all requests across the entire scenario
    requests.sort(key=lambda r: r[1])
    return requests, bursty_users_count, steady_users_count


# ---------------------------------------------------------------------------
# Core Simulation Engine
# ---------------------------------------------------------------------------


def run_comparison_simulation(
    users: int = 100,
    requests_per_user: int = 50,
    window_seconds: int = 10,
    limit: int | None = None,
    pattern: str = "uniform",
) -> ComparisonResponse:
    """Simulates synthetic traffic across all five rate limiting algorithms."""
    effective_limit = (
        limit if limit is not None else max(1, int(requests_per_user * 0.4))
    )
    total_requests = users * requests_per_user

    # Generate identical traffic pattern for all algorithms
    traffic, bursty_users_count, steady_users_count = generate_synthetic_traffic(
        users=users,
        requests_per_user=requests_per_user,
        window_seconds=window_seconds,
        pattern=pattern,
    )

    results: list[AlgorithmResult] = []
    base_time = 10000.0

    for algo_key, display_name, factory in ALGORITHMS_REGISTRY:
        clock = VirtualClock(start_time=base_time)
        latencies_ms: list[float] = []

        allowed_count = 0
        blocked_count = 0
        bursty_allowed = 0
        steady_allowed = 0

        # Run under isolated virtual time context
        with unittest.mock.patch("time.time", side_effect=clock):
            limiter = factory(effective_limit, window_seconds)

            for user_id, t_offset, is_bursty in traffic:
                clock.current_time = base_time + t_offset
                t0 = time.perf_counter()
                is_permitted = limiter.is_allowed(user_id)
                t1 = time.perf_counter()

                latencies_ms.append((t1 - t0) * 1000.0)

                if is_permitted:
                    allowed_count += 1
                    if is_bursty:
                        bursty_allowed += 1
                    else:
                        steady_allowed += 1
                else:
                    blocked_count += 1

        allowed_pct = (
            round((allowed_count / total_requests) * 100.0, 2)
            if total_requests > 0
            else 0.0
        )
        blocked_pct = (
            round((blocked_count / total_requests) * 100.0, 2)
            if total_requests > 0
            else 0.0
        )
        avg_latency = (
            round(sum(latencies_ms) / len(latencies_ms), 4) if latencies_ms else 0.0
        )

        # Fairness computations
        bursty_total = bursty_users_count * requests_per_user
        steady_total = steady_users_count * requests_per_user

        b_pct = (
            round((bursty_allowed / bursty_total) * 100.0, 2)
            if bursty_total > 0
            else 0.0
        )
        s_pct = (
            round((steady_allowed / steady_total) * 100.0, 2)
            if steady_total > 0
            else 0.0
        )

        if bursty_total > 0 and steady_total > 0:
            diff = b_pct - s_pct
            if diff > 5.0:
                favors = "bursty"
            elif diff < -5.0:
                favors = "steady"
            else:
                favors = "neutral"
        else:
            favors = "neutral"

        tradeoff_meta = TRADEOFFS_CATALOG[algo_key]

        results.append(
            AlgorithmResult(
                algorithm=algo_key,
                display_name=display_name,
                allowed=allowed_count,
                blocked=blocked_count,
                allowed_pct=allowed_pct,
                blocked_pct=blocked_pct,
                avg_latency_ms=avg_latency,
                tradeoffs=TradeoffData(**tradeoff_meta),
                fairness=FairnessData(
                    bursty_users_count=bursty_users_count,
                    steady_users_count=steady_users_count,
                    bursty_users_allowed=bursty_allowed,
                    bursty_users_total=bursty_total,
                    bursty_users_allowed_pct=b_pct,
                    steady_users_allowed=steady_allowed,
                    steady_users_total=steady_total,
                    steady_users_allowed_pct=s_pct,
                    favors=favors,
                ),
            )
        )

    scenario_meta = ScenarioConfig(
        users=users,
        requests_per_user=requests_per_user,
        window_seconds=window_seconds,
        limit=effective_limit,
        pattern=pattern,
        total_requests=total_requests,
    )

    return ComparisonResponse(scenario=scenario_meta, results=results)


# ---------------------------------------------------------------------------
# API Route
# ---------------------------------------------------------------------------


@router.get("/compare", response_model=ComparisonResponse)
def compare_algorithms(
    request: Request,
    users: int = Query(default=100, ge=1, le=1000, description="Total synthetic users"),
    requests_per_user: int = Query(
        default=50, ge=1, le=500, description="Requests sent per user"
    ),
    window: int = Query(
        default=10, ge=1, le=300, description="Window duration in seconds"
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=1000,
        description="Per-user allowed limit (defaults to 40% of requests)",
    ),
    pattern: str = Query(
        default="uniform",
        pattern="^(uniform|skewed)$",
        description="Traffic pattern: 'uniform' or 'skewed'",
    ),
    format: str | None = Query(
        default=None, description="Output format: 'json' or 'html'"
    ),
) -> Any:
    """Executes a comparative benchmark across all 5 rate-limiting algorithms."""
    sim_result = run_comparison_simulation(
        users=users,
        requests_per_user=requests_per_user,
        window_seconds=window,
        limit=limit,
        pattern=pattern,
    )

    # Content negotiation: check ?format= query param or Accept header
    accept = request.headers.get("accept", "")
    wants_html = (format == "html") or ("text/html" in accept and format != "json")

    if wants_html:
        context = {
            "scenario": sim_result.scenario.model_dump(),
            "results": [r.model_dump() for r in sim_result.results],
        }
        return templates.TemplateResponse(
            request=request, name="compare.html", context=context
        )

    return sim_result
