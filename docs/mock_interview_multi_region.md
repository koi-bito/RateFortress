# Mock System Design Interview: Multi-Region Distributed Rate Limiter

These are my walkthrough notes for an advanced interview on designing a globally distributed rate limiter operating across multiple geographic regions with low latency.

---

## 1. Network Physics vs Strict Consistency

In a single-region setup, gateway workers access a local Redis cluster over local VPC fiber with round-trip times well under 1 ms.

In a multi-region deployment across continents, network latency sets a hard limit:
- US-East to EU-West: roughly 75 to 90 ms round trip.
- US-West to APAC: roughly 110 to 130 ms round trip.

If a client has a global limit of 100 requests per minute and can hit US and European gateways interchangeably, we face a tradeoff:
- If we require strict global consistency on every call, every European request must contact a central store in the US before answering. Latency jumps to 90 ms, violating our latency target.
- If regions evaluate requests independently, eventual consistency creates a window where an abuser could send 100 requests in the US and 100 in Europe within the synchronization lag.

---

## 2. Architectural Approaches Evaluated

### Approach 1: Centralized Global Redis
Deploying a single primary Redis in US-East and having European and Asian gateways call it over cross-region VPC peering fails immediately. Adding 80 to 130 ms of latency to every international API call is unacceptable for user-facing applications.

### Approach 2: Active-Active Asynchronous CRDT Replication
Running a Redis cluster in each region and syncing counters asynchronously in the background using conflict-free replicated data types keeps local evaluations fast (under 1 ms). However, during the 150 to 300 ms sync window, an abuser can consume double their quota. This is acceptable for anti-scraping rules, but risky for billing meters.

### Approach 3: Static Regional Quota Partitioning
Dividing global quotas statically across regions based on expected traffic shares avoids cross-region network calls completely. The downside is rigidity: if a European user moves their traffic to US hours, they get throttled early while their European quota sits unused.

### Approach 4: Dynamic Batched Token Leasing (Recommended Model)
Each region runs a local Redis cluster and local gateway instances. A global quota coordinator tracks overall quota pools.

Local gateways do not acquire tokens one by one from the global store. Instead, they pre-fetch token leases in batches, such as 20 to 50 tokens with a 5-second lease window.

Requests are served out of the pre-fetched local batch in under 1 ms. When the local batch dips below 20% remaining, an asynchronous background task requests the next lease from the coordinator. This keeps per-request latency local while capping over-admission risk to the active lease buffer.

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

## 4. Handling Partitions and Cable Cuts

If cross-region fiber cuts disconnect US-East from EU-West:
1. Local autonomy: Local regions detect lease acquisition timeouts and continue operating independently.
2. Degraded policy: Regions can switch to conservative local quotas (such as allowing 50% of nominal quota) during the outage.
3. Fail-open for public routes: Standard content endpoints remain reachable.
4. Fail-closed for expensive routes: Paid third-party invocations are clamped to prevent financial runaway.
5. Reconnection: When connectivity returns, uncommitted lease differentials reconcile without manual intervention.

---

## 5. Defense Talking Points

- Latency is the primary constraint: Adding 80 ms of latency to every single API request is not an option. Any design claiming strict global ACID consistency across continents for high-throughput rate limiting ignores network reality.
- Most clients stay in one region: Around 95% of API traffic originates from a client's primary region where their servers run. Only roaming mobile users frequently cross continents.
- Layered defense: Pair global batched token leasing with an edge CDN rate limiter for raw layer-7 volumetric protection, reserving RateFortress for fine-grained tenant tier enforcement.
