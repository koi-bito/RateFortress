# RateFortress — Horizontal Scaling & Redis Cluster Architecture

These are my architectural notes on scaling RateFortress horizontally across Redis Cluster nodes and multi-region topologies.

---

## 1. Single-Node Redis Limits

RateFortress relies on Redis 7 as its distributed state store. A single Redis instance on a standard machine handles between 40,000 and 100,000 operations per second.

When traffic scales past that, single-node setups hit physical boundaries:
1. Network interface saturation: Ingress TCP packet handling and OS socket backlogs fill up under heavy concurrent traffic.
2. CPU core saturation: Redis executes commands on a single event-loop thread. Even with I/O threads enabled, Lua scripts execute sequentially.
3. RAM limits: Storing tens of millions of active keys on one machine creates a single point of failure.

Scaling beyond these limits requires partitioning state across an elastic Redis Cluster.

---

## 2. Redis Cluster & Hash Slot Partitioning

Redis Cluster partitions keyspace into 16,384 logical hash slots:
`Slot = CRC16(Key) % 16384`

Each master node owns a slice of slots. When a client sends a command, the Redis client driver hashes the key and routes the request directly to the node responsible for that slot.

---

## 3. The Multi-Key Lua Constraint

In Redis Cluster, Lua scripts cannot access keys that hash to different slots. If a script accesses two keys on different slots, Redis returns a CROSSSLOT error and fails the command.

To keep related keys on the same slot, Redis supports hash tags: only the substring inside `{...}` is hashed. For example, `{user_123}:tokens` and `{user_123}:meta` hash to the exact same slot because only `user_123` is hashed.

In RateFortress, I designed every rate limiting script to operate strictly on a single key (`KEYS[1]`):

- Token Bucket operates on `KEYS[1]` only (the client hash).
- Leaky Bucket operates on `KEYS[1]` only (the queue hash).
- Sliding Window Log operates on `KEYS[1]` only (the sorted set).
- Sliding Window Counter operates on `KEYS[1]` only (the window hash).
- GCRA operates on `KEYS[1]` only (the TAT timestamp string).

Because every rate limiting script operates on exactly one key, RateFortress runs across a Redis Cluster without running into cross-slot errors.

---

## 4. Multi-Region Topologies

This was kept single-region by design. In multi-region deployments, sending a rate limit check across continents adds 80 to 200 ms of latency. A rate limiter must respond in under 2 ms, so synchronous transatlantic checks are out of the question.

### Regional Quota Partitioning
Divide the global quota proportionally across regions based on expected traffic:
- Global limit: 1,000 req/min
- US-East (60% traffic): 600 req/min in local Redis
- EU-West (30% traffic): 300 req/min in local Redis
- AP-South (10% traffic): 100 req/min in local Redis

The tradeoff is rigidity: if a European user bursts traffic while US traffic is idle, they get throttled early.

### Local Fast-Path with Asynchronous Sync
Each region runs local Redis clusters enforcing local limits. Usage is batched and asynchronously synced across regions every second.

This keeps latency under 1 ms for all local requests while allowing bounded over-admission during the brief sync window.

---

## 5. Notes for Cluster Migration

1. Client driver: Switch to redis.cluster.RedisCluster and redis.asyncio.cluster.RedisCluster for automatic slot discovery.
2. Namespace tagging: Enforce hash tags on compound keys, such as `{tenant:123:user:456}:route_api`.
3. Topology refresh: Enable cluster topology refreshes so the gateway picks up re-sharded nodes automatically.
