# What I Got Wrong (and Right) About Rate Limiting: Post-Launch Retrospective

These are my personal reflections after releasing RateFortress, running load tests with Locust and k6, and testing edge cases.

---

## 1. What I Got Wrong Initially

### Assumption 1: Sliding Window Log is always the best algorithm because it is exact.
In theory, Sliding Window Log is mathematically exact with no boundary spikes. In practice at scale, it is usually the worst choice for high-traffic public routes.

Storing every request timestamp in a Redis Sorted Set consumes a lot of memory. At 10 million active users, storing all those timestamps takes dozens of gigabytes of RAM and burns CPU cycles running range deletions. Sliding Window Counter or GCRA provides almost identical boundary protection with constant O(1) memory.

### Assumption 2: In-memory rate limiters are fine for smaller apps.
As soon as you run Uvicorn with multiple workers, you have multiple isolated memory spaces. A user who is supposed to be limited to 10 requests per minute can send 40 requests per minute simply by hitting alternating worker processes. Externalizing state to Redis is necessary even on a single multi-worker instance.

### Assumption 3: A bigger Redis connection pool will fix latency under load.
When testing 500 concurrent users with synchronous Redis, expanding the pool from 10 to 100 connections did nothing for median latency. The bottleneck was not the pool size. It was that every synchronous read blocked the single thread running the ASGI event loop. Switching to redis.asyncio fixed it immediately.

---

## 2. What Worked Well

### Validation 1: Atomic Lua Scripting
In my 50-thread concurrent stress tests, Lua scripts kept over-admission at 0%. Running the read, check, and update inside an atomic script completely prevented check-then-set race conditions.

### Validation 2: The Fail-Open Circuit Breaker
When I simulated Redis dropping out mid-test, the circuit breaker tripped open and let requests through. That preserved API availability instead of throwing 500 errors across every route.

### Validation 3: Proactive Rate Limit Headers
Sending X-RateLimit-Limit, Remaining, and Retry-After headers on every response allowed well-behaved clients to slow down before hitting 429 errors.

---

## 3. Notes on What Could Come Next

If I took this further, two areas stand out:
1. Multi-region replication: Partitioning quotas or using token leases so regions do not wait on cross-continent round trips.
2. Behavioral scoring: Detecting automated scrapers based on request timing jitter instead of relying purely on static IP rules.
