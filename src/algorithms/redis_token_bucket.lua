-- Atomic Token Bucket Rate Limiter
-- KEYS[1] = bucket key (e.g., "token_bucket:{user_id}")
-- ARGV[1] = capacity (maximum tokens allowed)
-- ARGV[2] = refill_rate (tokens added per second)
-- ARGV[3] = now (current Unix epoch timestamp in seconds)
-- ARGV[4] = requested_tokens (tokens to consume, defaults to 1; 0 means inspect/refill only)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4]) or 1

-- Fetch existing bucket state
local bucket = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if not tokens or not last_refill then
    -- Brand new bucket for this client
    tokens = capacity
    last_refill = now
else
    -- Compute refill based on elapsed wall-clock time
    local elapsed = math.max(0, now - last_refill)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_refill = now
end

local allowed = 0
if requested > 0 and tokens >= requested then
    tokens = tokens - requested
    allowed = 1
elseif requested == 0 then
    allowed = 1
end

-- Persist atomic state
redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)

-- Set TTL: buffer time to refill from zero to capacity, with a 3600-second baseline
local fill_time = math.ceil(capacity / refill_rate)
local ttl = math.max(3600, fill_time * 2)
redis.call("EXPIRE", key, ttl)

-- Compute retry_after seconds (time until at least 1 token is available)
local retry_after = 0
if tokens < 1.0 then
    local deficit = 1.0 - tokens
    retry_after = math.ceil(deficit / refill_rate)
    if retry_after < 1 then
        retry_after = 1
    end
end

-- Return: [allowed (1 or 0), remaining_tokens (integer floor), retry_after_seconds]
return {allowed, math.floor(tokens), retry_after}
