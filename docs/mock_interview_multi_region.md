# Mock System Design Interview #2 — Multi-Region Distributed Rate Limiter

This document captures an advanced senior/staff-level system design interview focusing on the hard distributed systems challenge: **building a globally distributed rate limiter operating across multiple geographical regions (US, EU, APAC) with sub-2ms latency**.

---

## 1. The Fundamental Problem: Speed of Light vs. Strict Consistency

In a single-region deployment, all gateway workers access an in-region Redis cluster over local VPC fiber ($< 0.8\text{ ms}$ round trip time).

In a global deployment:
- **US-East (N. Virginia) to EU-West (Frankfurt):** $\approx 75 - 90\text{ ms}$ RTT.
- **US-West (Oregon) to APAC (Tokyo):** $\approx 110 - 130\text{ ms}$ RTT.

### The CAP Dilemma:
If a client has a global quota of **$100\text{ requests / minute}$** and can route requests interchangeably to US and EU gateways:
- If we demand **Strict Global Consistency (CP)**, every request in EU must synchronously contact a centralized database in US before responding $\rightarrow$ **Latency explodes from $1\text{ ms}$ to $90\text{ ms}$**, violating the non-functional latency SLO ($< 2\text{ ms}$).
- If we demand **Local Low Latency (AP)**, regions must evaluate requests independently $\rightarrow$ **Eventual consistency creates a window of over-admission** where an attacker could fire 100 requests in US and 100 in EU simultaneously within the cross-region sync window.

---

## 2. Architectural Approaches Evaluated

```
                     Approach Comparison
┌──────────────────────────────┬───────────────────┬───────────────────┐
│ Approach                     │ Latency (p99)     │ Accuracy          │
├──────────────────────────────┼───────────────────┼───────────────────┤
│ 1. Centralized Global Redis  │ 80–120 ms (FAIL)  │ 100% Strict       │
│ 2. Active-Active CRDT Sync   │ < 1.5 ms  (PASS)  │ Soft (±20% burst) │
│ 3. Static Quota Partitioning │ < 1.0 ms  (PASS)  │ Fragmented Quota  │
│ 4. Batched Token Leasing     │ < 1.2 ms  (PASS)  │ 98–99% Accurate   │
└──────────────────────────────┴───────────────────┴───────────────────┘
```

### Approach 1: Centralized Single-Leader Redis (Rejected)
- Deploy primary Redis in `us-east-1`; EU and APAC gateways call it over cross-region VPC peering.
- **Verdict:** **REJECTED.** Adds 80–130ms latency to every international API call. Catastrophic for user-facing applications.

### Approach 2: Active-Active Asynchronous CRDT Replication
- Run a full Redis cluster in each region (US, EU, APAC).
- Replicate counters across regions asynchronously using conflict-free replicated data types (CRDTs / PN-Counters).
- **Behavior:**
  - Local increments are instantaneous ($< 1\text{ ms}$).
  - Counters sync in the background over cross-region links within $150 - 300\text{ ms}$.
- **Tradeoff:** A transient burst split across two regions within 200ms can admit up to $2\times$ the configured limit before synchronization converges. Acceptable for bot abuse prevention; unacceptable for billing / credit enforcement.

### Approach 3: Static Regional Quota Partitioning (Token Slicing)
- Divide global quota statically based on expected regional traffic shares:
  - Global Quota: $100\text{ req/min}$
  - US-East ($60\%$ traffic): $60\text{ tokens}$
  - EU-West ($40\%$ traffic): $40\text{ tokens}$
- **Advantage:** Zero cross-region communication during request evaluation; each region runs standard RateFortress Token Bucket / GCRA locally.
- **Drawback:** Inflexible. If a European developer travels to the US or shifts traffic during US business hours, they get throttled at 60 req/min despite having 40 unused tokens sitting idle in Frankfurt.

### Approach 4: Dynamic Batched Token Leasing (The Recommended Production Model)
- **Architecture:**
  - Each region runs a local Redis cluster and local RateFortress instances.
  - A global token lease coordinator acts as the source of truth for total available quota chunks.
  - Local gateways do **not** acquire 1 token per request from the global store. Instead, they request **token leases in batches** (e.g. chunks of $10 - 50\text{ tokens}$ with a 5-second TTL).
  - High-frequency requests are served out of the pre-fetched local batch in $< 1\text{ ms}$.
  - When the local batch falls below a low-water mark (e.g. 20% remaining), an asynchronous background thread requests the next lease from the coordinator.
- **Advantage:**
  - Per-request latency remains purely local ($< 1\text{ ms}$).
  - Cross-region calls are amortized: $1\text{ global call per 50 user requests}$ rather than $1\text{ per request}$.
  - Over-admission risk is strictly capped to the unexpired local lease buffer ($< 5\%$).

---

## 3. High-Level Multi-Region Topology

```
             [Global Anycast DNS / Cloudflare Route]
             ┌───────────────────┴───────────────────┐
             ▼                                       ▼
    [Region: US-East-1]                     [Region: EU-West-1]
┌───────────────────────────┐           ┌───────────────────────────┐
│ Gateway Pool (FastAPI)    │           │ Gateway Pool (FastAPI)    │
│ └── Local Token Bucket    │           │ └── Local Token Bucket    │
│                           │           │                           │
│ Local Redis Cluster       │           │ Local Redis Cluster       │
│ (Local hot cache: <1ms)   │           │ (Local hot cache: <1ms)   │
└─────────────┬─────────────┘           └─────────────┬─────────────┘
              │                                       │
              │ (Async Quota Sync / Batch Leases)     │
              ▼                                       ▼
  ┌───────────────────────────────────────────────────────────────┐
  │         Global Quota Coordinator (Multi-Region Raft/CRDT)     │
  │     - Allocates token batch leases (chunk size: 20 tokens)    │
  │     - Tracks aggregate consumption across regions             │
  └───────────────────────────────────────────────────────────────┘
```

---

## 4. Handling Network Partitions & Split-Brain (Transatlantic Cable Cut)

If cross-region fiber cuts disconnect US-East from EU-West:
1. **Local Autonomy:** Local regions immediately detect lease acquisition timeouts.
2. **Degraded Mode Policy:**
   - **Proportional Cap:** Regions switch to conservative local quotas (e.g., local region permits at most $50\%$ of nominal limit).
   - **Fail-Open for Public Endpoints:** Continue serving standard traffic to maintain platform availability.
   - **Fail-Closed for Expensive Endpoints:** Prevent financial loss on OpenAI/Stripe downstream invocations.
3. **Reconnection & Convergence:** When connectivity restores, uncommitted lease differentials reconcile via additive reconciliation without requiring manual operator intervention.

---

## 5. Senior Interviewer Defense Talking Points

- **Latency is King:** In API infrastructure, an extra 80ms of overhead on every request is a dealbreaker. Any design claiming "strict global ACID consistency across continents for high-volume rate limiting" reveals a fundamental misunderstanding of network physics.
- **The 95/5 Rule:** 95% of API clients originate from a single primary geographic region (where their backend servers run). Only roaming mobile users or multi-region distributed clients span continents.
- **Defense in Depth:** Combine global batched token leasing with a fast edge CDN rate limiter (Cloudflare/Fastly WAF) at Layer 7 for raw DDoS, reserving RateFortress for fine-grained multi-tier business quota management.

