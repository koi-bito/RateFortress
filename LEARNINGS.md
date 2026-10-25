# RateFortress — Daily Engineering Log & Learnings

A structured record of architectural decisions, DSA insights, failure modes, and lessons learned across the 29-week engineering roadmap.

---

## 📅 Week 0 — Foundations (Days 1–5)

### Day 1 — Why Rate Limiting Exists
- **Core Concept:** Rate limiting protects services from denial of service (DoS), cascading downstream failures, brute-force/credential-stuffing attacks, and unfair resource monopolization ("noisy neighbors" in multi-tenant environments).
- **Two Concrete Scenarios Without Rate Limiting:**
  1. *Resource Exhaustion / Database Crash:* An unthrottled search or analytics endpoint receiving 10,000 requests/sec will saturate database connection pools and CPU, knocking the entire application offline for all legitimate users.
  2. *Economic / Free-Tier Exploitation:* Attackers can script automated accounts to spam free-tier generative AI endpoints or SMS verification services, running up thousands of dollars in third-party API bills in minutes.

### Day 2 — The Five Core Algorithms
- **Payments API vs. Search Autocomplete:**
  - *Payments API:* **Token Bucket** or **Sliding Window Log**. Payments cannot tolerate boundary bursts that overwhelm banking settlement gateways, but users should never face silent drops; Token Bucket allows small bursts while strictly metering the steady-state refill rate.
  - *Search Autocomplete:* **Sliding Window Counter** or **Fixed Window Counter**. Search suggestions require ultra-low latency (<5ms) and high throughput. An approximation like Sliding Window Counter has $O(1)$ memory, negligible CPU overhead, and dropping a stray keystroke is acceptable compared to adding latency to query evaluation.

### Day 3 — DSA: Hashmaps, Deques & Circular Buffers
- **Why `collections.deque` over `list`:** A standard Python `list` is a dynamic array. Popping an element from the front (`list.pop(0)`) requires shifting all remaining $n-1$ elements in memory, yielding $O(n)$ time complexity per eviction. For a sliding window log handling high request volume, $O(n)$ evictions destroy performance. `collections.deque` is implemented as a doubly linked block list, providing true $O(1)$ amortized `popleft()` and `append()`.

### Day 4 — DSA: Heaps & Consistent Hashing
- **Min-Heaps vs. Sorted Lists:** A min-heap provides $O(\log n)$ insertion and $O(1)$ peek ($O(\log n)$ pop) for priority operations. Maintaining a sorted list requires $O(n)$ insertion time. For dynamic priority queues, a min-heap scales efficiently.

### Day 5 — Project Scoping & Manual Simulation
- **Algorithm Differences Under Boundary Bursts:** Simulating 5 requests / 10s window at boundary $t=9, 10$: Fixed Window allows 5 requests at $t=9$ and another 5 at $t=10$ (10 requests in 2 seconds = 2x limit spike). Sliding Window Log and Sliding Window Counter both detect the rolling 10-second footprint and reject the boundary burst.

---

## 📅 Week 1 — Environment Setup & Project Scaffold (Days 6–10)

### Day 6 — Modular Architecture Separation
- **Why separate `algorithms/`, `middleware/`, and `api/`:** Clean separation of concerns allows testing pure algorithmic logic in isolation, swappable storage engines, and embedding limiters into any ASGI/gRPC middleware without rewriting business logic.

### Day 7 — Commit Message Conventions
- **Standard Convention Adopted:** `feat:`, `test:`, `perf:`, `refactor:`, `docs:`, `fix:`, `ci:`.

### Day 8 — Test-Driven Development (TDD)
- **Why Write Tests First:** Establishes clear boundary conditions (limit - 1, limit, limit + 1, rollover resets) before asynchronous HTTP concurrency complicates debugging.

### Day 9 — Unified Benchmark Harness
- **Why a Single Benchmark Harness:** Ensures unbiased, apples-to-apples comparisons by isolating algorithmic data structures as the sole independent variable.

### Day 10 — Week 1 Review
- **Reflection:** Scaffolded core directory structure, configured isolated Python virtual environment, integrated pytest, established baseline benchmark harness, and validated clean code formatting.

---

## 📅 Week 2 — Fixed Window & Sliding Window Log (Days 11–15)

### Day 11 — Fixed Window Counter Mechanics
- **The Boundary Burst Problem:** Fixed Window evaluates `current_window = int(now // window_seconds)`. Traffic clustered at window boundaries allows up to $2 \times \text{limit}$ in a rolling window of length $T$.
- **Complexity:** $O(1)$ time, $O(1)$ memory per client.

### Day 12 — Testing & Benchmarking Fixed Window
- **Throughput:** Achieved **~2.82M req/s** in in-memory pure Python.

### Day 13 — Sliding Window Log Mechanics
- **Precision with Deques:** Sliding Window Log records timestamps in a `collections.deque`. Timestamps $\le \text{now} - \text{window}$ are popped from the left.
- **Tradeoff:** Storing every timestamp consumes $O(N)$ memory per active client.

### Day 14 — Testing & Benchmarking Sliding Window Log
- **Throughput:** Achieved **~3.47M req/s** in in-memory pure Python.

### Day 15 — Empirical Comparison (Fixed Window vs. Sliding Window Log)
- **Script Evidence:** `benchmarks/compare_window_boundary.py` verified that with limit=5/10s, Fixed Window leaked 10/10 requests while Sliding Window Log blocked requests 6 through 10.

---

## 📅 Week 3 — Sliding Window Counter, Token Bucket & Leaky Bucket (Days 16–21)

### Day 16 — Sliding Window Counter Mechanics
- **Weighted Approximation Math:** $\text{Estimated} = (\text{Previous Count} \times \text{Weight of Previous}) + \text{Current Count}$, where $\text{Weight of Previous} = 1 - (\text{Elapsed} / \text{Window})$.
- **Why It Beats Both Predecessors:** Provides boundary smoothing with strictly $O(1)$ memory (only 2 counters per client).

### Day 17 — Token Bucket Mechanics
- **Lazy Refill Calculation:** Tokens are refilled lazily on each request: $\Delta t = \text{now} - \text{last\_refill}$, $\text{new\_tokens} = \min(\text{capacity}, \text{tokens} + \Delta t \times \text{refill\_rate})$.
- **Industry Standard:** Accommodates legitimate short-term spikes up to `capacity` while guaranteeing long-term consumption never exceeds `refill_rate`.

### Day 18 — Leaky Bucket Mechanics
- **Constant Egress:** Requests enter a queue and leak out at a strictly uniform rate, completely eliminating downstream spikes.

### Day 19 — Full 5-Algorithm Benchmark Suite
- **Throughput Profile (Pure Python, 10k requests, 100 users):**
  - Sliding Window Log: **~3.47M req/s**
  - Fixed Window Counter: **~2.82M req/s**
  - Leaky Bucket: **~2.58M req/s**
  - Sliding Window Counter: **~2.12M req/s**
  - Token Bucket: **~2.07M req/s**

### Day 20 — DSA Practice Day: Core Patterns
- **LeetCode Patterns:** Monotonic deque (#239), Circular buffer (#362), and Min-heap stream (#703).

### Day 21 — Week 3 Review & Milestone Complete
- **Status:** All 5 foundation algorithms fully implemented and benchmarked.

---

## 📅 Week 4 — FastAPI Middleware Layer I (Days 22–27)

### Day 22 — ASGI Architecture & Uvicorn
- **What is ASGI:** Asynchronous Server Gateway Interface is the modern Python asynchronous standard. Uvicorn manages raw OS network sockets and event loops, invoking FastAPI's ASGI interface.

### Day 23 — Middleware Dispatch Pipeline
- **Request Interception:** `RateLimitMiddleware` intercepts requests before routing or database execution, returning early HTTP 429 responses.

### Day 24 — Rate Limit Headers on Every Response
- **Client Transparency:** Returns `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` on every response, enabling client SDKs to proactively throttle before hitting errors.

### Day 25 — Per-Endpoint Quota Isolation
- **Granular Throttling:** Strict limits on expensive operations (`/api/expensive-endpoint`) without penalizing lightweight read endpoints.

### Day 26 — API Key Security & Tier Multipliers
- **Why Headers over Query Parameters:** Headers prevent credentials from being leaked to browser histories, reverse proxy logs, and `Referer` headers. Tier multipliers: Free = 1x, Paid = 10x, Enterprise = 50x.

### Day 27 — DSA Practice: Hashing & Design Patterns
- **Patterns:** LRU Cache (#146), Insert Delete GetRandom O(1) (#381), Design Twitter (#355).

---

## 📅 Week 5 — FastAPI Middleware Layer II — Tiering, Resilience & Load Prep (Days 28–33)

### Day 28 — Tiered Rate Limits with Priority Queues
- **Min-Heap Scheduling:** Implemented `PriorityRequestQueue` using `heapq` with tie-breaking counters. Enterprise (0) and Paid (1) requests are dequeued and serviced before Free (2) or Anonymous (3) requests.
- **Production Placement:** In production, request prioritization belongs at the API Gateway or ingress reverse-proxy layer (e.g. Envoy, Nginx, or an external SQS/Redis queue). Placing queues inside individual web worker processes leads to fragmented, desynchronized queues across multiple server nodes and risks dropped requests on worker restart.

### Day 29 — Endpoint Trie for Prefix Matching
- **Why Trie Beats String Scans:** Scanning an array of $N$ routes with regex or string comparisons incurs $O(N \times M)$ overhead per request. An `EndpointTrie` executes in $O(K)$ time where $K$ is the number of path segments (usually 2–5), completely independent of how many hundreds of route rules are registered.
- **Hierarchical Inheritance:** Parent rules (e.g., `/api/admin`) automatically govern nested routes (`/api/admin/users`, `/api/admin/settings`) unless explicitly overridden by a more specific child rule.

### Day 30 — Full Middleware Integration Testing
- **End-to-End Verification:** `tests/test_middleware_integration.py` confirmed trie prefix inheritance, enterprise 50x quota scaling, and circuit breaker fail-open behavior. All 46 tests pass across the suite.

### Day 31 — Live Request Burst Throttling
- **Empirical Demonstration:** `loadtests/manual_load_burst.py` fired 30 sequential requests at `/api/test` (limit=10). Requests #1–#10 succeeded with decreasing `X-RateLimit-Remaining` counts (9 down to 0). Request #11 triggered the first HTTP 429, and requests #11–#30 were all throttled with `Retry-After: 6`.

### Day 32 — Circuit Breaker & Resilience Policies
- **Fail-Open vs. Fail-Closed:**
  - *RateFortress Policy (Fail-Open):* If the storage backend (Redis) or rate limiter raises exceptions, the circuit breaker trips to `open` and allows incoming traffic to pass through. For customer-facing APIs, maximizing availability and avoiding false-positive outages takes precedence over temporary unthrottled access during an infrastructure incident.
  - *Contrast with Payments (Fail-Closed):* For payment gateways or banking settlement systems, failing closed is non-negotiable. An unthrottled payment service could execute duplicate charges, overdraft accounts, or allow fraudulent charge loops that inflict direct financial damage.

### Day 33 — Week 5 Review & Completion
- **Milestone Achieved:** The complete ASGI middleware pipeline is finished, hardened with trie matching, priority queuing, and fail-open resilience. Ready for Week 6: Distributed Redis Backend and Lua script atomicity.

---

## 📅 Week 6 — Redis Backend I (Days 34–39)

### Day 34 — Why In-Memory Breaks in Production & Redis Setup
- **The Split-Brain In-Memory Dilemma:** When an API scales horizontally across $M$ server instances behind a load balancer (e.g., AWS ALB, Nginx), each process running with an in-memory `defaultdict` maintains an isolated, private counter. If a client has a rate limit of 10 req/min, an abuser can round-robin requests across 5 instances and successfully execute $5 \times 10 = 50$ requests per minute. To enforce a true global quota across an elastic cluster, state must be externalized to a shared, high-throughput in-memory data store like Redis.
- **Verification:** Verified Redis connectivity and multi-client key synchronization with `scripts/test_redis_connection.py`.

### Day 35 — Redis Fixed Window & The Danger of GET-then-SET
- **Atomic `INCR` vs. `GET`-then-`SET` Race Condition:** If two concurrent requests arrive simultaneously at Server A and Server B when the counter is at 4 (limit=5):
  1. Server A executes `GET key` $\to$ receives `4`.
  2. Server B executes `GET key` $\to$ receives `4`.
  3. Server A checks `4 < 5` (allowed) and executes `SET key 5`.
  4. Server B checks `4 < 5` (allowed) and executes `SET key 5`.
  - Both requests were permitted, and the actual total requests served is now 6 (violating the limit of 5).
  - With Redis `INCR`, the operation is executed in a single atomic cycle inside Redis's single-threaded event loop. Server A's `INCR` returns `5` (allowed); Server B's `INCR` returns `6` (immediately blocked).

### Day 36 — Redis Sliding Window Counter & Distributed Tradeoffs
- **Throughput vs. Distributed Correctness:** In-memory execution achieves ~2.1M req/s, whereas Redis pipeline execution achieves ~13.9k req/s. While in-memory is 150x faster on a raw CPU microbenchmark, 13.9k req/s is still ~7x higher than the concurrency ceiling of a typical ASGI Python application worker (~2k req/s). In distributed production systems, correctness under horizontal scale always trumps localized microbenchmark speed.
- **TTL Strategy:** Expiring the window key after $2 \times \text{window\_seconds} + 2$ ensures the counter lives long enough to serve as the `previous_window` for the subsequent cycle while guaranteeing zero permanent memory leaks in Redis.

### Day 37 — Sliding Window Log via Redis Sorted Sets (ZSET)
- **Why Sorted Sets Beat Plain Lists:**
  1. *Score as Timestamp:* Using float Unix epoch timestamps as the sorted set score allows pruning all timestamps older than the sliding window boundary with a single command: `ZREMRANGEBYSCORE key 0 (now - window)`. This executes in $O(\log N + M)$ time.
  2. *Constant-Time Cardinality:* `ZCARD key` returns the exact number of active requests in $O(1)$ time.
  3. *Exact Header Calculation:* Inspecting the oldest entry with `ZRANGE key 0 0 WITHSCORES` in $O(\log N)$ gives the exact timestamp needed to calculate `Retry-After = oldest + window - now`.
  4. With a plain Redis `LIST`, timestamps cannot be ordered or range-pruned by value without scanning the entire list from client space ($O(N)$ network transfer).

### Day 38 — Test Isolation & Redis Database Indexing
- **Why Dedicated DB Indexes Matter:** Redis supports logical database indexes (DB 0 to 15). Tests run `FLUSHDB` before and after every test function to guarantee a clean slate. If tests ran on DB 0 (the development/staging database), running the test suite would instantly purge developer cache keys, active session tokens, and mock data. Isolating test execution strictly to DB 1 prevents catastrophic test pollution.

### Day 39 — DSA Practice: Tries vs. Hashmaps for Routing
- **Trie Time Complexity:** Both insert and search in a segment-based Trie take $O(K)$ time, where $K$ is the number of path segments (typically 2 to 5 in REST APIs), completely independent of the total number of registered routes ($N$).
- **Why Tries Beat Hashmaps for Prefixes:** With a hashmap, prefix inheritance requires $O(K)$ lookups slicing every prefix substring or iterating through all $N$ keys. A Trie naturally stops at the deepest matching branch node with a rule, supporting hierarchical wildcard inheritance (`/api/admin/*`) with zero backtracking.

---

## 📅 Week 7 — Redis Backend II — Lua Scripts, Atomicity & Eviction (Days 40–45)

### Day 40 — Token Bucket via Redis + Lua Scripts
- **Why Simple Commands Fail for Token Bucket:** Unlike Fixed Window Counter which can rely on a single atomic `INCR`, Token Bucket must track both floating-point `tokens` and the timestamp `last_refill`. Performing `HMGET`, calculating the elapsed refill in application memory, and writing back with `HMSET` creates a classic Time-Of-Check to Time-Of-Use (TOCTOU) race condition where concurrent requests overwrite each other's decrements.
- **Lua Execution Semantics:** Redis guarantees that Lua scripts execute atomically within the server's single-threaded event loop. By registering `redis_token_bucket.lua`, the entire read-refill-check-decrement-write-expire pipeline executes as a single isolated primitive, eliminating interleaving without distributed locks.

### Day 41 — Leaky Bucket via Redis + Lua Scripts
- **Discrete Leakage & Constant Egress:** Implemented `redis_leaky_bucket.lua` using a Redis Hash (`queue_size`, `last_leak`). Elapsed time since `last_leak` calculates integer request leakage, and remaining capacity determines whether new requests are queued.
- **Behavioral Contrast Confirmed on Redis:** Under identical sudden traffic bursts, Token Bucket instantly admits bursts up to `capacity`, while Leaky Bucket strictly limits the queue fill and forces a constant egress drain rate, preventing downstream saturation.

### Day 42 — Atomicity Deep Dive & Race Condition Elimination
- **Exposing the Day 37 Check-Then-Insert Race Condition:** In our Day 37 Redis Sliding Window Log, `zcard(key)` and `zadd(key, ...)` were executed as two separate calls. Under a 50-thread concurrent barrage with `limit=10`, multiple threads inspected `ZCARD` before any thread wrote to the sorted set, admitting 18 to 24 requests instead of the strict quota of 10.
- **Atomic Lua Remediation:** Replaced the multi-call pipeline with `redis_sliding_window_log.lua`, encapsulating `ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`, and `EXPIRE` into a single script. Verified with `tests/test_redis_concurrency.py`: across repeated concurrent runs, exactly 10 requests were permitted and 40 blocked (0% over-admission).

### Day 43 — Distributed Multi-Instance Validation
- **Cluster Quota Enforcement:** Validated multi-instance behavior with `tests/test_distributed_multi_instance.py`. Two independent FastAPI server instances alternating requests under a shared limit of 10 successfully served 5 requests each. The 11th request was blocked with HTTP 429 across both instances, proving that rate limiting is enforced globally rather than per-node.
- **Preventing Cluster Multiplication:** Without externalized Redis state, scaling from 1 to $M$ instances multiplies client quotas by $M$. Externalizing state to Redis guarantees the nominal limit holds regardless of how many horizontal worker nodes are provisioned.

### Day 44 — Key Eviction & TTL Strategy
- **Auditing Immortal Keys:** Confirmed that 100% of Redis keys across all 5 algorithms establish an explicit TTL upon creation/access. Fixed window keys expire in `window_seconds + 1`, sliding window counter in `2 * window_seconds + 2`, and bucket hashes in `max(3600, 2 * refill/drain time)`.
- **Why `volatile-lru` Beats `allkeys-lru`:** In production clusters shared between caching and rate limiting, `allkeys-lru` risks evicting permanent configuration or auth metadata. Because RateFortress guarantees all rate-limiting keys have active TTLs, `volatile-lru` safely recycles stale rate limiter keys under memory pressure without touching non-volatile data.

### Day 45 — Week 6–7 Review & Milestone Complete
- **Milestone Achieved:** Distributed Redis Backend complete! All 5 rate limiting algorithms now run with full multi-instance synchronization, atomic Lua execution, zero race conditions under concurrent load, 100% key TTL coverage, and comprehensive integration testing. Ready for Week 8: Load Testing with Locust.
