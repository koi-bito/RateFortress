# RateFortress — Senior Technical Capstone Deep Dive

**Duration:** ~15 minutes  
**Format:** Architectural Whiteboard & Codebase Walkthrough  
**Target Audience:** Staff / Principal Engineers and Technical Interviewers  

---

## 0:00 – 2:30: Motivation, Core Failure Modes & Problem Framing

- **The Problem:** Rate limiting looks trivial when taught in tutorials: `redis.incr(key)`. In production, naive implementations cause severe outages:
  1. *Horizontal Multi-Instance Multiplier:* In-memory limits multiply allowed traffic by $M$ across $M$ worker instances.
  2. *Check-Then-Set Race Conditions:* In a distributed system, a separate `GET` then `SET` leaks 100%+ over-admission under concurrent bursts.
  3. *Window Boundary Bursts:* Fixed windows allow $2\times$ traffic spikes at reset boundaries.
  4. *ASGI Event Loop Starvation:* Synchronous database calls in modern async Python servers (Uvicorn/FastAPI) freeze the single operating system thread running the event loop.
- **Project Scope:** RateFortress implements 6 distinct rate limiting algorithms in pure Python and distributed Redis 7, backs them with atomic Lua scripts, provides pluggable ASGI middleware with trie routing and tier multipliers, and wraps everything in comprehensive Prometheus, Grafana, Loki, and OpenTelemetry observability.

---

## 2:30 – 6:00: Deep Dive on the 6 Algorithms & Mathematical Formulations

- **Fixed Window Counter:** $O(1)$ memory, fastest execution, but vulnerable to boundary spikes.
- **Sliding Window Log:** Stores exact timestamps in a doubly-linked deque or Redis Sorted Set (`ZSET`). Prunes expired entries via `ZREMRANGEBYSCORE`. 100% mathematically exact, but $O(N)$ memory cost per client.
- **Sliding Window Counter:** Blends previous and current window counts:
  $$\text{Estimate} = \text{Count}_{\text{prev}} \times \left(1 - \frac{\text{elapsed}}{\text{window}}\right) + \text{Count}_{\text{current}}$$
  Gives smooth boundary protection with strictly $O(1)$ RAM.
- **Token Bucket:** Lazy refill calculation on each request:
  $$\Delta t = \text{now} - \text{last\_refill}, \quad \text{tokens} = \min(\text{capacity}, \text{tokens} + \Delta t \times \text{refill\_rate})$$
  Accommodates natural client bursts up to bucket capacity while capping sustained consumption.
- **Leaky Bucket:** Constant egress rate. Rejects bursts to protect fragile downstream services.
- **GCRA (Generic Cell Rate Algorithm):** Stripe's production algorithm. Replaces floating-point token math with a single Theoretical Arrival Time (TAT):
  $$\text{new\_TAT} = \max(\text{now}, \text{TAT}) + \text{emission\_interval}$$
  Permits bursts up to burst tolerance $\tau = T \times (\text{limit} - 1)$ while tracking only a single scalar timestamp in Redis (~32 bytes).

---

## 6:00 – 9:00: The Concurrency Elimination via Atomic Lua Scripts

- **The TOCTOU Race Condition:** Explain our Day 42 concurrency benchmark where 50 concurrent threads hammered a quota of 10. Non-atomic Redis pipelines admitted 22 requests (120% leak) because all threads read count $< 10$ before any thread wrote.
- **The Solution:** Authored custom Lua scripts (`redis_token_bucket.lua`, `redis_gcra.lua`, `redis_sliding_window_log.lua`, `redis_sliding_window_counter.lua`, `redis_leaky_bucket.lua`).
- **Why Lua Works:** Redis executes Lua scripts as an isolated atomic primitive on its single command loop. All checks, refills, and state mutations execute in a single tick with 0% race conditions.
- **The Multi-Node Cluster Trap:** Show why RateFortress scripts operate strictly on `KEYS[1]`, avoiding the dreaded Redis Cluster `CROSSSLOT` error.

---

## 9:00 – 12:00: Event Loop Architecture & The Async Redis Migration

- **Why Sync Redis Failed:** During Day 48 Locust load testing at 500 concurrent users, median latency was 17ms. Expanding the connection pool from 10 to 100 connections did nothing because synchronous socket reads blocked Uvicorn's OS thread.
- **The Migration to `redis.asyncio`:** Rewrote middleware and limiters with non-blocking async calls. Under identical 500-user load, median latency dropped from 17ms to 13ms (-23.5%) and p95 tail latency dropped from 88ms to 52ms (-40.9%).
- **Fail-Open Circuit Breaker:** Walk through `src/middleware/circuit_breaker.py`. Trips to `OPEN` after 5 failures to ensure storage blips never cause an API black hole.

---

## 12:00 – 15:00: Full-Stack Observability, CI/CD, and Hard-Won Lessons

- **Observability:** Walk through Prometheus metrics (`ratefortress_requests_total`, `ratefortress_limiter_overhead_seconds`), Loki structured JSON logs with client key masking, OpenTelemetry tracing spans, and live Grafana dashboards.
- **CI/CD Parity:** Discuss our post-mortem incidents: why `pytest-asyncio` must be explicitly declared, why `conftest.py` must set environment flags before top-level imports evaluate, and why `127.0.0.1` must be preferred over `localhost` on dual-stack IPv6 runners.
- **Summary:** RateFortress bridges theoretical algorithms, distributed concurrency, production resilience, and cloud operations.
