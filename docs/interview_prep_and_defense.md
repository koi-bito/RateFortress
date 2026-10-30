# RateFortress — System Design Mock Interview Guide & Defense

This guide provides structured, battle-tested answers to the most common system design and distributed systems interview questions for **RateFortress**, including capacity estimation flashcards, single-region and multi-region architectural trade-offs, and security defenses.

---

## 1. 60-Second Elevator Pitch

### "Walk me through this project."
> *"RateFortress is a production-grade distributed rate limiting engine and API gateway built from first principles in Python and Redis.
>
> In high-scale architectures, rate limiters protect downstream databases from cascading failures and enforce multi-tenant API tiers. However, most off-the-shelf implementations either suffer from the 2x window boundary burst problem, consume excessive memory at scale, or succumb to check-and-set race conditions under concurrent load.
>
> I built RateFortress to solve these challenges directly. It implements six distinct algorithms—Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, Leaky Bucket, and GCRA (Generic Cell Rate Algorithm)—backed by Redis with atomic Lua scripts. It features hierarchical route matching via an Endpoint Trie, circuit breaker fail-open resilience, trusted proxy CIDR validation, behavioral bot analysis, a live `/compare` benchmarking engine, and complete observability via Prometheus, Grafana, Loki, and OpenTelemetry.
>
> In local benchmarks, the engine achieves over 3.3 million requests/second in pure Python and 6,700 requests/second on Redis, with verified 0% over-admission under concurrent thread stress tests."*

---

## 2. Fast Back-of-the-Envelope Estimation Flashcards

When an interviewer asks: *"Scale this to 1 Million requests/second globally with 10 Million daily active users"*:

| Metric | Answer / Work Shown |
| :--- | :--- |
| **Peak Throughput** | $1,000,000\text{ req/sec}$ peak, $400,000\text{ req/sec}$ average. |
| **Network Bandwidth** | $250\text{ bytes/transaction} \times 1\text{M req/sec} = 250\text{ MB/s} = \mathbf{2.0\text{ Gbps}}$ network ingress/egress. |
| **Memory (GCRA)** | $10\text{M keys} \times 124\text{ B/key} \approx \mathbf{1.24\text{ GB}}$ ($\mathbf{1.86\text{ GB}}$ with safety buffer). |
| **Memory (Token Bucket)**| $10\text{M keys} \times 144\text{ B/key} \approx \mathbf{1.44\text{ GB}}$ ($\mathbf{2.16\text{ GB}}$ with safety buffer). |
| **Memory (Sliding Window Log)**| $10\text{M keys} \times 7.3\text{ KB/key} \approx \mathbf{73\text{ GB}}$ ($\mathbf{109.5\text{ GB}}$ with buffer) — **$58.8\times$ more memory!** |
| **Redis Shard Count** | $1\text{ primary node} \approx 50,000\text{ Lua ops/sec}$. $1,000,000 / 50,000 = \mathbf{20\text{ primary shards}}$ ($+ 20\text{ multi-AZ replicas} = 40\text{ nodes}$). |
| **Gateway CPU Cores** | $1\text{ core} \approx 8,000\text{ req/sec}$ async ASGI. $1\text{M} / 8\text{k} = \mathbf{125\text{ vCPUs}}$ ($16\times\text{ c7g.2xlarge}$ instances). |

*(See full mathematical derivations in [docs/capacity_planning.md](file:///c:/GITHUB%20Repos/RateFortress/docs/capacity_planning.md)).*

---

## 3. Deep-Dive Technical Questions & Defenses

### Q1: "How did you prevent concurrency race conditions in a distributed environment?"
- **The Failure Mode:**
  Under high concurrent load (e.g. 50 threads firing simultaneously against a limit of 10), naive rate limiters execute a **check-then-set** sequence (`GET` count, check if $< 10$, then `SET` count + 1). Because all reads occur before any writes commit, all 50 threads observe count $< 10$, admitting 18 to 25 requests—a catastrophic 150% over-admission leak.
- **The Solution:**
  We consolidated all read, eviction, bounds-checking, insertion, and TTL expiration logic into **atomic Lua scripts** (`redis_sliding_window_log.lua`, `redis_sliding_window_counter.lua`, `redis_token_bucket.lua`, `redis_leaky_bucket.lua`, `redis_gcra.lua`). Because Redis executes Lua scripts as a single atomic transaction on its single-threaded event loop, no interleaving operations can occur.
- **Empirical Evidence:**
  Stress testing with 50 concurrent threads in `tests/test_redis_concurrency.py` proved exactly 10 requests allowed and 40 blocked (strict 0% leakage).

---

### Q2: "What is GCRA, and why did Stripe choose it over Token Bucket?"
- **The Math:**
  GCRA (Generic Cell Rate Algorithm) represents rate limits as an **emission interval** ($T = \text{period} / \text{limit}$) and a **burst tolerance** ($\tau = \text{limit} \times T - T$). Instead of keeping track of a token counter and last refill timestamp, GCRA tracks a single scalar: the **Theoretical Arrival Time (TAT)**.
  $$\text{proposed\_tat} = \max(\text{now}, \text{current\_tat}) + T$$
  If $\text{proposed\_tat} - \text{now} > \tau + T$, the cell arrives too early and is rejected.
- **Why It Wins on Redis:**
  - Token Bucket requires a Redis Hash (`tokens`, `last_refilled`) $\rightarrow 144\text{ bytes}$ and multiple hash field parses.
  - GCRA stores a single integer/float string timestamp $\rightarrow 124\text{ bytes}$, saving memory and achieving **3.3M req/sec** local throughput vs 2.1M for Token Bucket.

---

### Q3: "What happens if Redis crashes or suffers network partition?"
- **The Failure Mode:**
  If an API gateway depends synchronously on Redis and Redis goes down, a naive gateway either throws HTTP 500 Internal Server Errors (taking down the entire business) or hangs on socket timeouts until worker threads exhaust.
- **The Solution:**
  We implemented a **Circuit Breaker** (`src/middleware/circuit_breaker.py`) wrapping all Redis calls:
  1. **CLOSED State:** Nominal operation; calls proceed to Redis with a strict 1.0-second socket timeout.
  2. **OPEN State:** After 5 consecutive Redis connection timeouts/errors, the circuit trips OPEN.
  3. **Fail-Open Policy:** While OPEN, RateFortress bypasses Redis entirely and allows requests through to upstream handlers. A degraded rate limiter is far better than a total API outage.
  4. **HALF-OPEN State:** After a 30-second cooldown, trial canary requests test Redis connectivity. If successful, the circuit resets to CLOSED.
- **Observability Signal:**
  Prometheus exposes `ratefortress_circuit_breaker_state{state="open"}` and Loki logs critical warnings.

---

### Q4: "How do you design rate limiting across multiple geographic regions?"
- **The Physical Constraint:**
  Transatlantic fiber latency between US-East and EU-West is $\approx 80\text{ ms}$ round-trip. Running synchronous global database checks introduces an unacceptable 80ms delay on every single request when our SLO is $< 2\text{ ms}$.
- **The Production Solution (Batched Token Leasing):**
  1. Each region runs a local Redis cluster and local RateFortress instances.
  2. A global token coordinator holds total quota pools.
  3. Local regions do not acquire 1 token per request; they pre-fetch **token leases in batches** (e.g. chunks of 20 tokens with a 5-second lease TTL).
  4. 95% of requests are evaluated against local memory in $< 1\text{ ms}$.
  5. Cross-region communication is amortized by $20\times$. If a transatlantic fiber cut occurs, regions fall back to local autonomous proportional limits without cascading outages.

*(See full whiteboarding script in [docs/mock_interview_multi_region.md](file:///c:/GITHUB%20Repos/RateFortress/docs/mock_interview_multi_region.md)).*

---

### Q5: "How does RateFortress defeat IP spoofing and bot abuse?"
- **Anti-Spoofing via Trusted Proxy CIDRs:**
  Attackers frequently spoof `X-Forwarded-For` with random IPs on every request. RateFortress uses right-to-left reverse proxy traversal: only hops originating from designated trusted CIDRs (e.g. AWS ALB or Cloudflare edge subnets) are unpacked. If an untrusted socket connects, headers are discarded and throttling binds to the socket IP.
- **Behavioral Timing Shield:**
  Automated bots fire requests with mechanical regularity (coefficient of variation $CV < 0.05$). RateFortress tracks inter-arrival jitter and automatically downgrades bot identities to a stricter tier ($0.2\times$ multiplier) without hard-blocking, avoiding false-positive outages.

---

## 4. Key Artifacts Cross-Reference
- [Capacity Planning & Math Estimations](file:///c:/GITHUB%20Repos/RateFortress/docs/capacity_planning.md)
- [Mock Interview #1: Single-Region Gateway](file:///c:/GITHUB%20Repos/RateFortress/docs/mock_interview_single_region.md)
- [Mock Interview #2: Multi-Region Global Topology](file:///c:/GITHUB%20Repos/RateFortress/docs/mock_interview_multi_region.md)
- [ADR-001: Token Bucket & GCRA Architecture Decision Record](file:///c:/GITHUB%20Repos/RateFortress/docs/ADR-001-algorithm-choice.md)
- [Red Team Adversarial Report](file:///c:/GITHUB%20Repos/RateFortress/docs/redteam_report.md)
- [Comparative Benchmark Analysis](file:///c:/GITHUB%20Repos/RateFortress/docs/comparative_benchmark_article.md)
