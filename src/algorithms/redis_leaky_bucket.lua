-- Atomic Leaky Bucket Rate Limiter
-- KEYS[1] = bucket key (e.g., "leaky_bucket:{user_id}")
-- ARGV[1] = capacity (maximum queue size / buffer slots)
-- ARGV[2] = leak_rate (requests drained per second)
-- ARGV[3] = now (current Unix epoch timestamp in seconds)
-- ARGV[4] = consume (1 to push a request into bucket; 0 to inspect without queuing)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local leak_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local consume = tonumber(ARGV[4]) or 1

-- Fetch existing state
local bucket = redis.call("HMGET", key, "queue_size", "last_leak")
local queue_size = tonumber(bucket[1])
local last_leak = tonumber(bucket[2])

if not queue_size or not last_leak then
    queue_size = 0
    last_leak = now
else
    local elapsed = math.max(0, now - last_leak)
    if queue_size > 0 then
        local leaked = math.floor(elapsed * leak_rate)
        if leaked > 0 then
            queue_size = math.max(0, queue_size - leaked)
            if queue_size == 0 then
                last_leak = now
            else
                last_leak = last_leak + (leaked / leak_rate)
            end
        end
    else
        last_leak = now
    end
end

local allowed = 0
if consume > 0 then
    if queue_size < capacity then
        queue_size = queue_size + 1
        allowed = 1
    else
        allowed = 0
    end
else
    allowed = 1
end

-- Persist atomic state
redis.call("HMSET", key, "queue_size", queue_size, "last_leak", last_leak)

-- Set TTL to ensure old keys cleanly expire
local drain_time = math.ceil(capacity / leak_rate)
local ttl = math.max(3600, drain_time * 2)
redis.call("EXPIRE", key, ttl)

local remaining = math.max(0, capacity - queue_size)
local retry_after = 0
if remaining == 0 then
    local time_to_next_leak = (1.0 / leak_rate) - (now - last_leak)
    retry_after = math.ceil(time_to_next_leak)
    if retry_after < 1 then
        retry_after = 1
    end
end

-- Return: [allowed (1 or 0), remaining_capacity (integer), retry_after_seconds, queue_size]
return {allowed, remaining, retry_after, queue_size}
