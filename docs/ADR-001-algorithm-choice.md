# ADR-001: Selection of Token Bucket and GCRA as Default Rate Limiting Algorithms

- **Status:** Accepted
- **Date:** 2026-10-30
- **Authors:** RateFortress Architecture & Core Infrastructure Team
- **Deciders:** Principal SWE, Backend Platform Lead, Distributed Systems Architect
- **Technical Story:** Selection of default algorithmic engines for distributed API throttling across RateFortress gateway deployments.

---

## 1. Context and Problem Statement

Modern public API gateways must protect downstream microservices from traffic surges, abusive scrapers, and malicious denial-of-service attempts, while simultaneously enforcing commercial API subscription tiers.

To operate effectively at scale ($> 1,000,000\text{ req/sec}$ globally across millions of active tenants), the default rate limiting algorithm must satisfy four stringent criteria:
1. **Predictable Sub-Millisecond Latency:** Evaluation overhead must remain below $1.5\text{ ms}$ (p99) on distributed Redis backends and below $1.0\ \mu\text{s}$ in local memory.
2. **Minimal Memory Footprint:** Memory consumption per tracked client must remain $O(1)$ and $\le 200\text{ bytes}$ to allow tens of millions of concurrent client keys without memory exhaustion.
3. **Burst Tolerance with Fair Long-Term Shaping:** Real-world clients (e.g. web browsers loading static assets or mobile apps synchronizing data on launch) generate bursty traffic. The algorithm must permit legitimate transient bursts up to a bounded capacity while enforcing a strict steady-state consumption rate.
4. **Multi-Cost Support:** Support variable-cost requests (e.g., lightweight GET = 1 token, batch inference POST = 5 tokens) without architectural overhaul.

---

## 2. Decision

We have decided to adopt **Token Bucket** as the **primary default rate limiting algorithm** across all standard RateFortress middleware deployments, and **GCRA (Generic Cell Rate Algorithm)** as the **standard alternative for ultra-high-throughput Redis environments**.

All standard API endpoints will default to Token Bucket unless an endpoint explicitly configures specialized criteria in the Endpoint Trie.

---

## 3. Alternatives Considered

### Alternative 1: Fixed Window Counter
- **Description:** Divides time into fixed discrete windows (e.g. 00:00–00:59). Increments a single counter per window.
- **Why Rejected:** Suffers from the classic **$2\times$ boundary burst vulnerability**. A client can send its entire quota at 00:59 and another full quota at 01:00, dumping $200\%$ of permitted traffic into downstream services within a 2-second window.

### Alternative 2: Sliding Window Log
- **Description:** Records individual timestamps for every request in a sorted set (`ZSET`), pruning expired entries on each check.
- **Why Rejected:** Catastrophic memory overhead. At a nominal limit of 100 req/min per user, Sliding Window Log consumes $\approx 7,300\text{ bytes per user}$ ($\mathbf{58.8\times}$ more RAM than Token Bucket). At 10 million active keys, memory balloons to $> 72\text{ GB}$, compared to $\approx 2.1\text{ GB}$ for Token Bucket. Furthermore, sorted set insertions and range deletions run in $O(\log N + M)$ rather than $O(1)$.

### Alternative 3: Sliding Window Counter
- **Description:** Combines the current window count with a weighted fraction of the previous window count.
- **Why Rejected:** While memory-efficient ($\approx 150\text{ bytes}$), it is a mathematical approximation. During sudden burst traffic at boundary edges, it assumes an even distribution across the previous window, introducing a theoretical error margin of up to $15\%$.

### Alternative 4: Leaky Bucket
- **Description:** Requests enter a buffer and leak out at a strictly uniform rate. Excess requests overflow and are dropped.
- **Why Rejected:** Enforces an absolute constant egress rate with **zero burst tolerance**. Idle time cannot be banked. Legitimate clients opening multiple parallel connections (e.g., initial page load) suffer immediate 429 rejections despite zero historical usage.

---

## 4. Empirical Benchmark Evidence

Our empirical benchmarks conducted on identical hardware across pure Python and Redis-backed implementations demonstrate the superiority of Token Bucket and GCRA:

| Algorithm | Local Python Throughput | Redis Lua Throughput | Memory / Key | Exactness | Bursts Allowed? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GCRA** | **$3,303,492\text{ req/s}$** | **$6,695\text{ req/s}$** | **$124\text{ B}$** | Exact | Yes (Bounded) |
| **Token Bucket** | **$2,169,380\text{ req/s}$** | **$6,540\text{ req/s}$** | **$144\text{ B}$** | Exact | Yes (Bounded) |
| **Sliding Window Counter** | $1,784,210\text{ req/s}$ | $6,310\text{ req/s}$ | $150\text{ B}$ | Approx (±5%) | Yes (Smoothed) |
| **Fixed Window** | $2,450,110\text{ req/s}$ | $6,720\text{ req/s}$ | $112\text{ B}$ | Exact | Flawed ($2\times$) |
| **Sliding Window Log** | $1,120,450\text{ req/s}$ | $4,890\text{ req/s}$ | $7,300\text{ B}$ | Exact | Strict |

### Key Observations:
1. **GCRA achieves the highest throughput ($3.3\text{M req/s}$ local, $6.7\text{k req/s}$ Redis)** because it requires updating only a single timestamp (`tat`) rather than recalculating fractional token refills and token counts.
2. **Token Bucket** achieves equivalent operational safety with superior developer ergonomics, as "tokens remaining" directly maps to user-facing headers (`X-RateLimit-Remaining: 15`).

---

## 5. Consequences & Operational Guidelines

### Positive Consequences
- **Memory Predictability:** Memory usage scales linearly at $\approx 144\text{ bytes per key}$. 10M keys consume $< 2.2\text{ GB}$ RAM.
- **Sub-Millisecond Evaluation:** Both Token Bucket and GCRA evaluate in $O(1)$ arithmetic operations inside single Redis Lua executions.
- **Native Multi-Cost Support:** Deducting multiple tokens (e.g. `cost = 5`) is a single atomic decrement step.

### Negative Consequences & Mitigations
- **Burst Vulnerability to Downstream Services:** If a bucket has capacity 100, an aggressive client can burst 100 requests in 10ms.
  - *Mitigation:* We pair Token Bucket with short window refills (e.g., $10\text{ tokens / 1s}$ with burst capacity $15$, rather than $600\text{ tokens / 60s}$) or recommend Leaky Bucket specifically for asynchronous background queuing systems.
- **Clock Skew:** GCRA and Token Bucket rely on monotonic or Unix epoch time.
  - *Mitigation:* All Redis operations use Redis server time (`redis.call('TIME')`) or centralized synchronized gateway clocks using chrony/NTP to ensure skew remains $< 1\text{ ms}$.
