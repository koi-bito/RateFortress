# RateFortress — Capacity Planning & Estimation

I put together these capacity planning calculations to figure out what it takes to scale RateFortress to 1,000,000 requests per second across a global gateway.

---

## 1. System Scale & Assumptions

| Parameter | Value | Notes |
| :--- | :--- | :--- |
| Peak Global Throughput | 1,000,000 req/sec | High-scale global gateway across all endpoints |
| Average Global Throughput | 400,000 req/sec | Typical diurnal baseline traffic |
| Total Daily Active Tenants / Keys | 10,000,000 | Unique clients, user IDs, or API keys per 24 hours |
| Concurrent Active Keys in 60s Window | 1,500,000 | Active keys whose state resides in hot memory |
| Target Rate Limit Evaluation Latency | <= 2.0 ms (p99) | Gateway latency budget |
| Gateway Availability Target | 99.999% | Max 5.26 minutes downtime per year |

---

## 2. Redis Memory Estimation by Algorithm

Each client key takes memory in Redis. The actual footprint depends on the data structure each algorithm uses.

### 2.1 Token Bucket
Token Bucket uses a single Redis Hash (tokens and last_refilled) or two float strings:
- Key name (`rf:tb:{client_id}`): ~32 bytes
- Field 1 (tokens float): 8 bytes
- Field 2 (last_refilled epoch float): 16 bytes
- Redis dictEntry + robj + jemalloc allocation overhead: ~64 bytes
- Key expiration metadata (TTL dict in Redis db): ~24 bytes
- Total Memory per Key: roughly 144 bytes

For 10,000,000 active keys, that gives:
10,000,000 * 144 bytes = 1.44 GB
Adding a 50% safety buffer for jemalloc memory fragmentation puts it around 2.16 GB.

---

### 2.2 Generic Cell Rate Algorithm (GCRA)
GCRA uses a single Redis String storing the theoretical arrival time:
- Key name (`rf:gcra:{client_id}`): ~34 bytes
- Value (tat timestamp string): ~18 bytes
- Redis string robj + dictEntry overhead: ~48 bytes
- Key expiration metadata (TTL): ~24 bytes
- Total Memory per Key: roughly 124 bytes

For 10,000,000 active keys:
10,000,000 * 124 bytes = 1.24 GB
With a 50% safety buffer, that is roughly 1.86 GB.

---

### 2.3 Sliding Window Counter
Sliding Window Counter uses a Redis Hash with two integer counters for current and previous windows:
- Total Memory per Key: roughly 150 bytes

For 10,000,000 active keys:
10,000,000 * 150 bytes = 1.50 GB
With a buffer, that comes out to about 2.25 GB.

---

### 2.4 Sliding Window Log
Sliding Window Log uses a Redis Sorted Set (ZSET). Every request adds a timestamp member and prunes old entries.

Assuming an average limit of 100 requests per minute per client:
- Key overhead and ZSet header: ~96 bytes
- Each request entry in the skiplist: member string (16 bytes) + score (8 bytes) + skiplist node pointer and dict entry (48 bytes) = 72 bytes
- Total Memory per Active Key: 96 + (100 * 72) = 7,296 bytes (around 7.3 KB per key)

For 10,000,000 active keys, that requires 73 GB of RAM, or roughly 109.5 GB with fragmentation overhead. I would not recommend Sliding Window Log at scale for this reason alone.

### Memory Comparison Summary Table

| Algorithm | Memory per Key | 10M Keys Total RAM | Relative Overhead vs GCRA |
| :--- | :--- | :--- | :--- |
| GCRA | 124 B | 1.86 GB | 1.0x (Most Efficient) |
| Token Bucket | 144 B | 2.16 GB | 1.16x |
| Sliding Window Counter | 150 B | 2.25 GB | 1.21x |
| Fixed Window Counter | 112 B | 1.68 GB | 0.90x (Boundary burst flaw) |
| Sliding Window Log | 7,300 B | 109.5 GB | 58.8x (Unviable at scale) |

---

## 3. Network Bandwidth & IOPS Calculations

At a peak of 1,000,000 requests per second:
- Redis EVALSHA invocation packet: roughly 180 bytes
- Response packet ([allowed, remaining, retry_after]): roughly 70 bytes
- Total bytes per rate limit check: 250 bytes

Aggregate network throughput:
1,000,000 req/sec * 250 bytes = 250 MB/s
250 MB/s * 8 bits/byte = 2.0 Gbps

This means the cluster needs standard 10 Gbps network interfaces across nodes.

---

## 4. Redis Cluster Sizing

Redis executes commands on a single main thread, and Lua scripts run synchronously on that thread.

### 4.1 Node Capacity
A single Redis 7 node executing atomic Lua scripts caps around 65,000 to 85,000 operations per second. Pushing past 80% CPU causes queueing delays and latency spikes. I set a target threshold of 50,000 operations per second per shard.

### 4.2 Required Primary Shards
1,000,000 req/sec / 50,000 ops/sec per node = 20 primary shards.

### 4.3 High Availability
Running one replica per primary shard across availability zones gives 40 total Redis nodes (20 primaries and 20 replicas).

### 4.4 Memory per Shard
With 20 primary shards and 10 million active keys taking about 2.16 GB for Token Bucket, each shard only holds around 108 MB of data. Memory is not the bottleneck here. CPU and network packet processing dictate cluster size.

---

## 5. Gateway Tier Sizing (FastAPI ASGI Workers)

An asynchronous FastAPI worker process handles between 8,000 and 12,000 requests per second per core when executing lightweight async Redis calls. Planning for 8,000 requests per second per core:

1,000,000 req/sec / 8,000 req/sec per core = 125 vCPUs.

Running 16 instances of 8-vCPU machines across three availability zones behind a network load balancer satisfies this capacity.

---

## 6. Architecture Envelope

```
[Global Traffic: 1,000,000 req/sec]
              │
    [Network Load Balancer] (Layer 4 TCP - 2.0 Gbps)
              │
    ┌──────────┴──────────┐
    ▼                     ▼
[Zone A: 6 Gateways]  [Zone B: 5 Gateways]  [Zone C: 5 Gateways]
(Total 16x 8-vCPU instances = 128 vCPUs running RateFortress ASGI)
              │
     [Redis Cluster (40 Nodes)]
     ├── 20 Primary Shards (Each handling 50k ops/sec, ~110 MB RAM)
     └── 20 Multi-AZ Read Replicas (Automated failover)
              │
    P99 Latency Budget: < 1.4ms
    Total Storage Footprint: < 5 GB
```
