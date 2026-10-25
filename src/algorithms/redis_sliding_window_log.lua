-- Atomic Sliding Window Log Rate Limiter
-- KEYS[1] = sorted set key (e.g., "sliding_log:{user_id}")
-- ARGV[1] = limit (maximum requests in sliding window)
-- ARGV[2] = window_seconds (window duration in seconds)
-- ARGV[3] = now (current Unix epoch timestamp in seconds)
-- ARGV[4] = member_id (unique request identifier)
-- ARGV[5] = consume (1 to record request if allowed, 0 to inspect without recording)

local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local member = ARGV[4] or tostring(now)
local consume = tonumber(ARGV[5]) or 1

local window_start = now - window

-- 1. Atomic cleanup of timestamps older than sliding window
redis.call("ZREMRANGEBYSCORE", key, 0, window_start)

-- 2. Atomic count of current requests in window
local count = redis.call("ZCARD", key)

local allowed = 0
if consume > 0 then
    if count < limit then
        redis.call("ZADD", key, now, member)
        redis.call("EXPIRE", key, window + 1)
        allowed = 1
        count = count + 1
    else
        allowed = 0
    end
else
    allowed = 1
end

local remaining = math.max(0, limit - count)

-- 3. Calculate retry_after seconds based on oldest entry in window
local oldest = redis.call("ZRANGE", key, 0, 0, "WITHSCORES")
local retry_after = 1
if oldest and #oldest >= 2 then
    local oldest_ts = tonumber(oldest[2])
    local expires_at = oldest_ts + window
    retry_after = math.max(1, math.ceil(expires_at - now))
end

-- Return: [allowed (1 or 0), remaining_quota, retry_after_seconds, count]
return {allowed, remaining, retry_after, count}
