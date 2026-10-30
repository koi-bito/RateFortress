# RateFortress — Capacity Planning & Back-of-the-Envelope Estimation

This document provides rigorous, production-grade capacity planning calculations for scaling **RateFortress** to serve a tier-1 public API gateway under high global load.

---

## 1. System Scale & Assumptions

| Parameter | Value | Notes |
| :--- | :--- | :--- |
| **Peak Global Throughput ($Q_{peak}$)** | **$1,000,000\text{ req/sec}$** | High-scale global gateway across all endpoints |
| **Average Global Throughput ($Q_{avg}$)** | **$400,000\text{ req/sec}$** | Typical diurnal baseline traffic |
| **Total Daily Active Tenants / Keys ($N_{active}$)** | **$10,000,000$** | Unique clients, user IDs, or API keys per 24 hours |
| **Concurrent Active Keys in 60s Window ($N_{window}$)**| **$1,500,000$** | Active keys whose state resides in hot memory |
| **Target Rate Limit Evaluation Latency ($L_{max}$)**| **$\le 2.0\text{ ms}$ (p99)** | Strict gateway latency budget |
| **Gateway Availability Target** | **$99.999\%$ ("Five Nines")**| Max 5.26 minutes downtime per calendar year |

---

## 2. Redis Memory Estimation by Algorithm

Each client key occupies memory in Redis. The memory footprint depends heavily on the rate limiting algorithm's data structures.

### 2.1 Token Bucket
- **Data Structure:** Single Redis Hash (`HMSET key tokens last_refilled`) or two float strings.
- **Payload Breakdown:**
  - Key name (`rf:tb:{client_id}`): $\sim 32\text{ bytes}$
  - Field 1 (`tokens` - float): $8\text{ bytes}$
  - Field 2 (`last_refilled` - epoch float): $16\text{ bytes}$
  - Redis `dictEntry` + `robj` + jemalloc allocation overhead: $\sim 64\text{ bytes}$
  - Key expiration metadata (`TTL` dict in Redis db): $\sim 24\text{ bytes}$
- **Total Memory per Key ($M_{TB}$):**
  $$\approx 144\text{ bytes}$$
- **Total Hot RAM for $10,000,000$ Active Keys:**
  $$10,000,000 \times 144\text{ bytes} \approx 1.44\text{ GB}$$
  *(With 50% safety buffer for jemalloc fragmentation: $\mathbf{\approx 2.16\text{ GB}}$)*

---

### 2.2 Generic Cell Rate Algorithm (GCRA)
- **Data Structure:** Single Redis String (`SET key tat_timestamp EX ttl`).
- **Payload Breakdown:**
  - Key name (`rf:gcra:{client_id}`): $\sim 34\text{ bytes}$
  - Value (`tat` - microsecond epoch float/int string): $\sim 18\text{ bytes}$
  - Redis string `robj` + `dictEntry` overhead: $\sim 48\text{ bytes}$
  - Key expiration metadata (`TTL`): $\sim 24\text{ bytes}$
- **Total Memory per Key ($M_{GCRA}$):**
  $$\approx 124\text{ bytes}$$
- **Total Hot RAM for $10,000,000$ Active Keys:**
  $$10,000,000 \times 124\text{ bytes} \approx 1.24\text{ GB}$$
  *(With 50% safety buffer: $\mathbf{\approx 1.86\text{ GB}}$)*

---

### 2.3 Sliding Window Counter
- **Data Structure:** Single Redis Hash with current and previous window buckets (`HMSET key curr_count prev_count`).
- **Total Memory per Key ($M_{SWC}$):**
  $$\approx 150\text{ bytes}$$
- **Total Hot RAM for $10,000,000$ Active Keys:**
  $$10,000,000 \times 150\text{ bytes} \approx 1.50\text{ GB}$$
  *(With buffer: $\mathbf{\approx 2.25\text{ GB}}$)*

---

### 2.4 Sliding Window Log (The Memory Pitfall)
- **Data Structure:** Redis Sorted Set (`ZSET`) where every request appends a timestamp member (`ZADD key now now`) and trims expired entries (`ZREMRANGEBYSCORE key 0 window_start`).
- **Assumed Limit per Client:** $100\text{ requests / minute}$.
- **Payload Breakdown:**
  - Key overhead + ZSet header (`dict` + `skiplist`): $\sim 96\text{ bytes}$
  - Each request member in skiplist:
    - Member string (timestamp): $\sim 16\text{ bytes}$
    - Double score: $8\text{ bytes}$
    - Skiplist node pointer + dict entry: $\sim 48\text{ bytes}$
    - Total per request entry: $\approx 72\text{ bytes}$
- **Total Memory per Active Key ($M_{SWL}$):**
  $$96\text{ bytes} + (100\text{ req} \times 72\text{ bytes}) \approx 7,296\text{ bytes } (\mathbf{\approx 7.3\text{ KB/key}})$$
- **Total Hot RAM for $10,000,000$ Active Keys:**
  $$10,000,000 \times 7.3\text{ KB} \approx 73\text{ GB!}$$
  *(With 50% fragmentation buffer: $\mathbf{\approx 109.5\text{ GB}}$)*

### Memory Comparison Summary Table
| Algorithm | Memory per Key | 10M Keys Total RAM | Relative Overhead vs GCRA |
| :--- | :--- | :--- | :--- |
| **GCRA** | **$124\text{ B}$** | **$1.86\text{ GB}$** | **$1.0\times$ (Most Efficient)** |
| **Token Bucket** | **$144\text{ B}$** | **$2.16\text{ GB}$** | **$1.16\times$** |
| **Sliding Window Counter** | **$150\text{ B}$** | **$2.25\text{ GB}$** | **$1.21\times$** |
| **Fixed Window Counter** | **$112\text{ B}$** | **$1.68\text{ GB}$** | **$0.90\times$** (Boundary burst flaw) |
| **Sliding Window Log** | **$7,300\text{ B}$** | **$109.5\text{ GB}$** | **$58.8\times$ (Unviable at scale)** |

---

## 3. Network Bandwidth & IOPS Calculations

### 3.1 Network Throughput to Redis
At peak load ($Q_{peak} = 1,000,000\text{ req/sec}$):
- **Request Packet Size:** Redis `EVALSHA` command invocation with arguments (`user_id`, `tokens`, `cost`, `now`) $\approx 180\text{ bytes}$.
- **Response Packet Size:** Integer array `[allowed, remaining, retry_after]` $\approx 70\text{ bytes}$.
- **Total Bytes per Rate-Limit Check:**
  $$180\text{ B (ingress)} + 70\text{ B (egress)} = 250\text{ bytes / transaction}$$

- **Aggregate Network Throughput:**
  $$\text{Throughput} = 1,000,000\text{ req/sec} \times 250\text{ bytes} = 250,000,000\text{ bytes/sec} = 250\text{ MB/s}$$
- In Gigabit Network terms:
  $$250\text{ MB/s} \times 8\text{ bits/byte} = \mathbf{2.0\text{ Gbps}}$$
  *(Peak network egress/ingress requires standard $10\text{ Gbps}$ or $25\text{ Gbps}$ cloud network interfaces across the cluster).*

---

## 4. Redis Cluster Sizing & CPU Constraints

Redis is single-threaded for core execution. While I/O threads handle network parsing in modern Redis 6/7, Lua scripts run strictly on the single main execution thread.

### 4.1 Single Redis Node Throughput Capacity
Empirical benchmarks on high-performance AWS c6g (Graviton2) / c7g (Graviton3) instances show:
- Standard single Redis 7 instance executing atomic Lua scripts:
  $$\text{Capacity}_{node} \approx 65,000 - 85,000\text{ Lua ops/sec}$$
- Operating at $>80\%$ CPU utilization causes latency spikes ($p99 > 5\text{ ms}$) due to queueing delays.
- Target conservative operating threshold per node:
  $$\mathbf{50,000\text{ ops/sec / shard}}$$

### 4.2 Required Primary Shards
$$\text{Num Primary Shards} = \frac{1,000,000\text{ req/sec}}{50,000\text{ ops/sec / node}} = \mathbf{20\text{ Primary Shards}}$$

### 4.3 High Availability & Replication
To survive hardware, network, or availability zone failures without downtime:
- 1 Replica per Primary Shard across independent Availability Zones (Multi-AZ).
- Total Shards = $20\text{ Primaries} + 20\text{ Replicas} = \mathbf{40\text{ Redis Nodes}}$.

### 4.4 Shard Memory Distribution
With 20 primary shards and 10M active keys ($\approx 2.16\text{ GB}$ total RAM for Token Bucket):
$$\text{RAM per Primary Node} = \frac{2.16\text{ GB}}{20} \approx 108\text{ MB}$$
- Memory is **not** the bottleneck for Token Bucket / GCRA — **CPU and network packet processing is the primary scaling bottleneck**.
- Recommended instance type: **AWS `cache.c7g.xlarge`** (4 vCPU, 6.74 GiB RAM, 12.5 Gbps network) or **`c6g.xlarge`**.
  - Provides ample memory headroom ($< 5\%$ memory utilization).
  - Maximizes single-core clock speed and network packet processing capacity.

---

## 5. Gateway Tier Sizing (FastAPI ASGI Workers)

### 5.1 Worker Throughput
- An asynchronous FastAPI ASGI gateway process (using `uvloop` + `httptools` + `redis.asyncio`) handles:
  $$\approx 8,000 - 12,000\text{ req/sec per vCPU}$$
- Target load per core: $8,000\text{ req/sec}$.

### 5.2 Required Gateway Cores
$$\text{Total Gateway Cores} = \frac{1,000,000\text{ req/sec}}{8,000\text{ req/sec / core}} = \mathbf{125\text{ vCPUs}}$$
- Deployment topology:
  - 16 instances of `c7g.2xlarge` (8 vCPU, 16 GiB RAM) distributed across 3 Availability Zones behind an AWS Network Load Balancer (NLB).

---

## 6. Summary Architecture Envelope

```
[Global Traffic: 1,000,000 req/sec]
              │
    [Network Load Balancer] (Layer 4 TCP - 2.0 Gbps)
              │
   ┌──────────┴──────────┐
   ▼                     ▼
[Zone A: 6 Gateways]  [Zone B: 5 Gateways]  [Zone C: 5 Gateways]
(Total 16x c7g.2xlarge instances = 128 vCPUs running RateFortress ASGI)
              │
    [Redis Cluster (40 Nodes)]
    ├── 20 Primary Shards (Each handling 50k ops/sec, ~110 MB RAM)
    └── 20 Multi-AZ Read Replicas (Instant automated failover)
              │
   P99 Latency Budget: < 1.4ms
   Total Storage Footprint: < 5 GB
```

