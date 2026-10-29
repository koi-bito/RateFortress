# RateFortress — System Design Mock Interview Guide & Defense

This guide provides structured, battle-tested answers to the most common system design and distributed systems interview questions for **RateFortress**.

---

## 1. 60-Second Elevator Pitch

### "Walk me through this project."
> *"RateFortress is a production-grade distributed rate limiting engine and API gateway built from first principles in Python and Redis.
>
> In high-scale architectures, rate limiters protect downstream databases from cascading failures and enforce multi-tenant API tiers. However, most off-the-shelf implementations either suffer from the 2x window boundary burst problem or succumb to check-and-set race conditions under concurrent load.
>
> I built RateFortress to solve these challenges directly. It implements five distinct algorithms—Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, and Leaky Bucket—backed by Redis with atomic Lua scripts. It features hierarchical route matching via an Endpoint Trie, circuit breaker fail-open resilience, a live `/compare` benchmarking engine, and a complete observability stack with Prometheus, Grafana, Loki, and OpenTelemetry.
>
> The system achieves 43,000+ requests/second in benchmarks with verified 0% over-admission under concurrent stress tests."*

---

## 2. Deep-Dive Technical Questions & Defenses

### Q1: "How did you prevent concurrency race conditions in a distributed environment?"
- **The Failure Mode:**
  Under high concurrent load (e.g. 50 threads firing simultaneously against a limit of 10), naive rate limiters execute a **check-then-set** sequence (e.g. `ZCARD` to count timestamps, followed by application logic, followed by `ZADD`). Because the reads occur before any writes commit, all 50 threads observe count $< 10$, resulting in 18 to 25 admitted requests—a catastrophic 150% over-admission leak.
- **The Solution:**
  We consolidated all read, eviction, bounds-checking, insertion, and TTL expiration logic into **atomic Lua scripts** (`redis_sliding_window_log.lua`, `redis_sliding_window_counter.lua`, `redis_token_bucket.lua`, `redis_leaky_bucket.lua`). Because Redis executes Lua scripts as a single atomic transaction on its single-threaded event loop, no interleaving operations can occur.
- **Empirical Evidence:**
  Stress testing with 50 concurrent threads in `tests/test_redis_concurrency.py` proved exactly 10 requests allowed and 40 blocked (strict 0% leakage).

---

### Q2: "What happens if Redis crashes or suffers network partition?"
- **The Failure Mode:**
  If an API gateway depends synchronously on Redis and Redis goes down, a naive gateway either throws HTTP 500 Internal Server Errors (taking down the entire business) or hangs on socket timeouts until worker threads exhaust.
- **The Solution:**
  We implemented a **Circuit Breaker** (`src/middleware/circuit_breaker.py`) wrapping all Redis calls:
  1. **CLOSED State:** Nominal operation; calls proceed to Redis with a strict 1.0-second socket timeout.
  2. **OPEN State:** After 5 consecutive Redis connection timeouts/errors, the circuit trips OPEN.
  3. **Fail-Open Policy:** While OPEN, RateFortress bypasses Redis entirely and allows requests through to upstream handlers. A degraded rate limiter is far better than a total API outage.
  4. **HALF-OPEN State:** After a 30-second cooldown, a trial request tests Redis connectivity. If successful, the circuit resets to CLOSED.
- **Observability Signal:**
  Prometheus exposes `ratefortress_circuit_breaker_state{state="open"}` and Loki logs critical warnings.

---

### Q3: "Why choose Token Bucket as the default rate-limiting algorithm?"
- **The Tradeoff:**
  - Real-world client traffic is naturally bursty. When a user opens a web application or mobile app, the client initiates 10–20 parallel requests for HTML, CSS, user profile data, and assets.
  - A rigid algorithm like Leaky Bucket drops these requests immediately, causing broken UI widgets.
  - Fixed Window allows boundary bursts up to $2\times$ the limit.
- **Why Token Bucket Wins:**
  Token Bucket decouples **burst tolerance** (bucket capacity $B$) from **sustained throughput** (refill rate $R$). Clients that are idle accumulate tokens up to capacity, allowing them to load their interface instantly, while malicious bots attempting continuous scraping are capped at the refill rate. It requires only $O(1)$ memory (two numbers: token count and last refill timestamp).

---

### Q4: "What is the memory scaling difference between Sliding Window Log and Sliding Window Counter?"
- **Sliding Window Log ($O(N)$ RAM):**
  - Stores every individual request timestamp in a Redis Sorted Set (`ZSET`).
  - If 100,000 active users send 1,000 requests per minute, Redis must store 100,000,000 64-bit integer elements—consuming **over 4 GB of expensive Redis RAM** just for rate limiter timestamps.
  - Trimming expired elements (`ZREMRANGEBYSCORE`) takes $O(\log N + M)$ CPU time.
- **Sliding Window Counter ($O(1)$ RAM):**
  - Stores only two integer counters per user: current window and previous window.
  - Memory consumption is strictly constant: **~48 bytes per user regardless of request volume**.
  - Approximates the rolling count using weighted interpolation with $< 0.05\%$ error.
- **Recommendation:**
  Use Sliding Window Log only for security-critical, low-frequency endpoints (e.g. login authentication, password reset, payment auth). Use Sliding Window Counter for general high-volume REST APIs.

---

### Q5: "How would you scale RateFortress to 10+ Redis nodes across multiple regions?"
1. **Sharding with Consistent Hashing:**
   - Hash client keys (`hash(user_id)`) across a ring of $K$ Redis instances using consistent hashing with virtual nodes. This distributes memory and throughput evenly across the cluster and minimizes key reshuffling when adding nodes.
2. **Multi-Region Active-Active Topology:**
   - In multi-region deployments (e.g. US-East, EU-Central, AP-Southeast), synchronizing individual requests across transoceanic fibers introduces 150ms+ latency penalties.
   - **Local Bucket with Asynchronous Sync:** Each regional gateway cluster maintains local rate limits backed by a regional Redis instance. A background worker periodically synchronizes aggregated usage counters between regions via Redis CRDTs (Conflict-Free Replicated Data Types) or Kafka events.
   - Alternatively, partition quotas per region (e.g. a global 100 req/s quota allocates 40 req/s to US, 40 to EU, and 20 to AP).

---

### Q6: "Why is blue-green deployment specifically valuable for a rate limiter?"
- **Cold-Start Vulnerability:**
  A hard restart of an API gateway clears all local in-memory states, connection pools, and circuit breaker metrics. When the server boots back up, it experiences a "cold-start storm" where incoming requests race against uninitialized caches.
- **Zero-Downtime Guarantee:**
  With blue-green deployment:
  1. The Green candidate container boots up, validates its Redis connection pool, and executes pre-flight healthchecks on an internal port.
  2. The traffic router atomically flips the traffic pointer from Blue to Green.
  3. In-flight requests on Blue drain gracefully with zero connection resets (0% packet drop).
  4. If an anomaly is detected, traffic can be rolled back to Blue in under 1 millisecond.

