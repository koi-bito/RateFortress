# RateFortress — Horizontal Scaling & Distributed Cluster Architecture

**Author:** RateFortress Systems Architecture  
**Status:** Architectural Specification & Scaling Roadmap  
**Target Topology:** Multi-Node Redis Cluster, Hash Slot Partitioning, Multi-Region Replication  

---

## 1. The Scaling Imperative: When Single-Node Redis Reaches Capacity

RateFortress relies on Redis 7 as its distributed state store. A single Redis instance running on a modern virtual machine (e.g., AWS EC2 `r6g.xlarge`) achieves between **40,000 and 100,000 operations per second**.

However, single-node architectures encounter hard physical limits:
1. **Network Interface Sockets (NIC Saturation):** Ingress TCP packet handling and OS socket backlogs become saturated when processing millions of concurrent HTTP/gRPC requests.
2. **CPU Core Saturation:** Redis processes commands on a single event-loop thread. Even with I/O threads enabled, complex Lua script evaluations run sequentially.
3. **RAM Ceiling & Blast Radius:** If 100 million active API keys store rate limiting state, single-node memory failure or failover causes complete global API downtime.

To scale RateFortress to millions of requests per second, state must be partitioned across an elastic **Redis Cluster**.

---

## 2. Redis Cluster Mechanics & Hash Slot Partitioning

Redis Cluster does not use consistent hashing rings with virtual nodes directly; instead, it partitions keyspace into **16,384 logical hash slots**:

$$\text{Slot} = \text{CRC16}(\text{Key}) \pmod{16384}$$

```
+---------------------------------------------------------------------------------+
|                                16,384 Hash Slots                                |
+------------------------+--------------------------------+-----------------------+
|  Node A: Slots 0..5460 |     Node B: Slots 5461..10922  | Node C: Slots 10923.. |
+------------------------+--------------------------------+-----------------------+
            ^                                ^                               ^
            |                                |                               |
      Client Key A                     Client Key B                    Client Key C
```

Each physical master node is assigned a subset of slots. When a client issues a command, the Redis client driver hashes the key and routes the request directly to the master node owning that slot.

---

## 3. The Multi-Key Lua Constraint: The `CROSSSLOT` Trap

In Redis Cluster, **Lua scripts are strictly forbidden from operating on keys that hash to different slots**. 

If a Lua script attempts:
```lua
redis.call("GET", "key_alpha") -- hashes to Slot 102
redis.call("GET", "key_beta")  -- hashes to Slot 8421
```
Redis halts execution and returns a fatal cluster error:
```
(error) CROSSSLOT Keys in request don't hash to the same slot
```

### Hash Tagging Solution: `{...}`
To force multiple related keys onto the identical node and slot, Redis supports **Hash Tags**: only the substring inside `{...}` is hashed.
```
{user_10492}:token_bucket  --> CRC16("user_10492") % 16384
{user_10492}:metadata      --> CRC16("user_10492") % 16384 (Identical Slot!)
```

### Why RateFortress Is Natively Cluster-Ready
RateFortress was architected from Day 1 to avoid multi-key script dependencies:
- `redis_token_bucket.lua`: Operates on `KEYS[1]` only (the client hash).
- `redis_leaky_bucket.lua`: Operates on `KEYS[1]` only (the queue hash).
- `redis_sliding_window_log.lua`: Operates on `KEYS[1]` only (the sorted set).
- `redis_sliding_window_counter.lua`: Operates on `KEYS[1]` only (the current/previous window hash).
- `redis_gcra.lua`: Operates on `KEYS[1]` only (the TAT timestamp string).

Because **every RateFortress rate limiting primitive operates on exactly one key**, RateFortress can run across a 1,000-node Redis Cluster with **zero `CROSSSLOT` errors**.

---

## 4. Multi-Region Active-Active Topologies: The Speed of Light

In a multi-region deployment (e.g. US-East, US-West, EU-Central, AP-Southeast), transmitting a rate-limiting check across oceans introduces 80–200ms latency:

```
[User in London] ---> [EU API Gateway] ---> [US-East Redis]  (120ms round-trip latency!)
```

A rate limiter must respond in sub-millisecond time (<2ms). Waiting 120ms for transatlantic synchronization destroys user experience.

### Architectural Solutions for Multi-Region Rate Limiting

#### Solution A: Local Quota Partitioning (Static or Dynamic Slicing)
Divide the global quota proportionally across regions:
- Customer contracted quota: 1,000 requests/minute
- Region US-East (60% traffic): Limit = 600 req/min (stored in US-East Redis)
- Region EU-West (30% traffic): Limit = 300 req/min (stored in EU Redis)
- Region AP-South (10% traffic): Limit = 100 req/min (stored in AP Redis)

*Tradeoff:* If an EU user suddenly bursts 500 requests, they are throttled even if global usage is low.

#### Solution B: Local Fast-Path with Asynchronous Global Synchronization
1. Every region maintains a local Redis cluster enforcing local limits.
2. In-flight usage is batched and asynchronously broadcast across regions via Kafka, AWS Kinesis, or Redis Streams.
3. Every second, local limits are adjusted based on peer regional reports.

*Tradeoff:* Eventual consistency. Under an coordinated global attack, an adversary can exceed limits by a bounded margin during the 1-second sync window. For 99.9% of SaaS businesses, this minor leakage is vastly preferred over adding 100ms latency to every legitimate request.

#### Solution C: Conflict-Free Replicated Data Types (CRDTs)
Using specialized active-active Redis Enterprise or KeyDB multi-master replication with PN-Counters (Positive-Negative Counters) or GCRA delta reconciliation.

---

## 5. Implementation Roadmap for RateFortress v2.0 Cluster

1. **Client Driver Migration:**
   Replace `redis.Redis` and `fakeredis` with `redis.cluster.RedisCluster` and `redis.asyncio.cluster.RedisCluster`.
2. **Key Namespace Tagging:**
   Update key generation to enforce explicit hash tags:
   `f"{{tenant:{tenant_id}:user:{user_id}}}:{algorithm}"`
3. **Cluster Health & Node Discovery:**
   Implement dynamic topology refresh (`cluster_error_retry_attempts=3`, `read_from_replicas=True` for read-only quota checks).

