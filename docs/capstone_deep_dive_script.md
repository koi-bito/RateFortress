# RateFortress — Capstone Deep Dive & Technical Walkthrough Notes

These are my talking notes for a 15-minute walkthrough of the RateFortress codebase and architecture.

---

## 0:00 to 2:30: Motivation, Core Failure Modes & Problem Framing

Rate limiting seems simple when looking at basic examples with a single counter. In real systems, several edge cases break naive implementations:
1. Multi-instance scaling: In-memory limits multiply allowed traffic across workers unless state is centralized.
2. Check-then-set race conditions: A separate read followed by a write lets concurrent bursts through.
3. Window boundary bursts: Fixed windows allow double the nominal traffic right across the reset boundary.
4. Event loop stalls: Synchronous Redis calls in an async server freeze the main event loop thread.

I built RateFortress to implement six algorithms in Python and Redis, back them with atomic Lua scripts, wrap them in FastAPI middleware, and wire up metrics and tracing to see how each behaves.

---

## 2:30 to 6:00: The Six Algorithms & Their Mechanics

- Fixed Window Counter: O(1) memory and fastest to compute, but lets up to 2x traffic pass if bursts straddle window boundaries.
- Sliding Window Log: Stores timestamps in a deque or Redis sorted set (ZSET) and trims old entries. Completely exact, but memory grows with traffic volume.
- Sliding Window Counter: Blends current and previous window counts using a weighted estimate. Smooths boundary bursts while keeping memory constant at two numbers per key.
- Token Bucket: Refills tokens lazily on each request based on elapsed time. Lets legitimate bursts through up to capacity while capping sustained consumption.
- Leaky Bucket: Enforces a steady leak rate. Rejects bursts completely to protect downstream services that cannot tolerate sudden spikes.
- GCRA (Generic Cell Rate Algorithm): Tracks a single theoretical arrival time per key. Gives strict rate shaping while storing only about 32 bytes of state in Redis.

---

## 6:00 to 9:00: Concurrency & Atomic Lua Scripts

On Day 42, I tested 50 concurrent threads against a limit of 10. When using non-atomic Redis pipelines, 22 requests slipped through because threads checked the counter before other threads incremented it.

To fix this, I moved the check and mutation logic into Redis Lua scripts. Redis runs Lua scripts atomically on its single execution thread, so check-and-increment operations execute in a single step with 0% over-admission.

All scripts operate strictly on a single key (`KEYS[1]`) so they run cleanly on Redis Cluster without cross-slot errors.

---

## 9:00 to 12:00: Event Loop Architecture & Async Redis

During load testing at 500 concurrent users, the synchronous redis client caused median latency to jump to 17 ms. Increasing connection pool size did not help because synchronous socket reads blocked Uvicorn's event loop.

I migrated the middleware and storage calls to redis.asyncio. Under the same 500-user load, median latency dropped from 17 ms to 13 ms because the event loop could process other requests while waiting on Redis responses.

I also added a circuit breaker in `src/middleware/circuit_breaker.py`. If Redis fails repeatedly, the breaker trips open and lets traffic pass rather than hanging every client connection.

---

## 12:00 to 15:00: Observability, CI/CD, and Lessons Learned

For observability, I wired up Prometheus counters and latency histograms, structured JSON logging for Loki with client ID masking, and OpenTelemetry tracing spans to measure limiter overhead.

In CI/CD, I ran into practical issues worth remembering: setting environment variables in conftest before top-level imports execute, and preferring 127.0.0.1 over localhost on Windows and GitHub Actions runners to avoid IPv6 connection delays.
