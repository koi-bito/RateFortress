# RateFortress — System Design Interview Guide & Defense

These are my preparation notes for discussing RateFortress in system design interviews, covering capacity sizing, architectural trade-offs, and failure recovery.

---

## 1. 60-Second Elevator Pitch

"RateFortress is a distributed rate limiting engine and API gateway I built in Python and Redis.

In real systems, rate limiters protect databases from cascading failures and enforce customer quotas. Most simple implementations suffer from boundary burst leaks, consume excessive memory, or have race conditions under concurrency.

I built RateFortress to address those issues directly. It implements six algorithms (Fixed Window, Sliding Window Log, Sliding Window Counter, Token Bucket, Leaky Bucket, and GCRA) backed by Redis Lua scripts. It also includes endpoint prefix matching with a trie, Circuit Breaker fail-open handling, trusted proxy checks, and Prometheus metrics.

In benchmarks, the in-memory Python limiters handle over 2 million requests per second, while the Redis Lua scripts process around 6,700 requests per second with zero concurrency leaks under 50-thread stress tests."

---

## 2. Capacity Estimation Quick Reference

When asked to size for 1 million requests per second with 10 million daily active keys:

- Peak Throughput: 1,000,000 req/sec peak, 400,000 req/sec average.
- Network Bandwidth: 250 bytes per check * 1,000,000 req/sec = 250 MB/s = 2.0 Gbps network ingress and egress.
- Memory for GCRA: 10M keys * 124 bytes per key is roughly 1.24 GB (about 1.86 GB with safety buffer).
- Memory for Token Bucket: 10M keys * 144 bytes per key is roughly 1.44 GB (about 2.16 GB with safety buffer).
- Memory for Sliding Window Log: 10M keys * 7.3 KB per key is roughly 73 GB (about 109.5 GB with buffer). This is over 45 times more memory than Token Bucket.
- Redis Shard Count: At 50,000 Lua operations per second per primary node, 1,000,000 / 50,000 = 20 primary shards. Adding multi-AZ replicas brings it to 40 nodes.
- Gateway Cores: At 8,000 async requests per second per core, 1,000,000 / 8,000 = 125 vCPUs.

---

## 3. Key Technical Questions & Answers

### How did you prevent concurrency race conditions in a distributed environment?
Under high concurrency, separate read and write steps cause check-then-set race conditions. If fifty threads read count < 10 before any thread commits an increment, all fifty requests pass through.

I solved this by moving the evaluation and update logic into atomic Redis Lua scripts. Because Redis executes Lua scripts on its single execution loop without interleaving other operations, check and increment occur in a single step. In my 50-thread stress tests, this dropped over-admission to 0%.

### What is GCRA and why is it useful compared to Token Bucket?
GCRA (Generic Cell Rate Algorithm) models rate limiting with an emission interval and a burst tolerance. Instead of storing tokens and a refill timestamp, GCRA tracks a single timestamp called the Theoretical Arrival Time (TAT).

In Redis, Token Bucket requires storing multiple hash fields (tokens and timestamp), taking around 144 bytes per key. GCRA only stores a single timestamp string (around 124 bytes), saving memory while running slightly faster.

### What happens if Redis crashes?
If an API gateway depends synchronously on Redis and Redis goes down, the gateway either throws 500 errors or hangs on socket timeouts until worker threads exhaust.

I built a circuit breaker in `src/middleware/circuit_breaker.py` wrapping all Redis calls. In the closed state, calls execute normally with a 1.0-second timeout. After five consecutive failures, the breaker trips open and fails open, letting traffic pass through to upstream handlers.

A degraded rate limiter is much better than taking down the entire API. After a 30-second cooldown, trial requests test connectivity before resetting to closed.

### How would you handle rate limiting across multiple regions?
This was kept single-region by design. Cross-region network latency (such as 80 ms between US and Europe) makes synchronous global database lookups impractical when the latency budget is under 2 ms.

In a multi-region setup, each region runs its own local Redis cluster and gateway instances. Rather than acquiring single tokens across regions, local gateways pre-fetch token batches (such as 20 tokens with a 5-second lease) from a central coordinator. Over 95% of requests evaluate locally in under 1 ms, and cross-region round trips are amortized across the batch. If a region loses cross-region connectivity, it falls back to local quotas without taking down the service.

### Why build this in Python rather than Go?
The Go comparison was not in scope for this project. My goal was implementing the core rate limiting algorithms and Redis Lua atomicity from scratch, profiling async event loop behavior in Python, and establishing reliable benchmarks without extra language overhead.

### How does RateFortress handle IP header spoofing?
Attackers often spoof X-Forwarded-For with random IPs on every request. I implemented trusted proxy checks that parse the header from right to left, only accepting client IPs from configured upstream proxy CIDRs. If a request comes directly from an untrusted IP, the spoofed header is ignored and the socket IP is used instead.

---

## 4. Documentation References

- Capacity Planning: docs/capacity_planning.md
- Single-Region Mock Interview: docs/mock_interview_single_region.md
- Multi-Region Mock Interview: docs/mock_interview_multi_region.md
- Architecture Decision Record: docs/ADR-001-algorithm-choice.md
- Benchmarks: BENCHMARKS.md
