-- Atomic Sliding Window Counter Rate Limiter
-- KEYS[1] = current window key (e.g., "swc:{namespace}:{user_id}:{current_id}")
-- KEYS[2] = previous window key (e.g., "swc:{namespace}:{user_id}:{prev_id}")
-- ARGV[1] = limit (maximum requests in window)
-- ARGV[2] = window_seconds (window duration in seconds)
-- ARGV[3] = weight_prev (weight of previous window, float between 0.0 and 1.0)
-- ARGV[4] = ttl (expiration time in seconds for current_key)
-- ARGV[5] = consume (1 to consume a slot if allowed, 0 to inspect without consuming)

local current_key = KEYS[1]
local prev_key = KEYS[2]

local limit = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local weight_prev = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local consume = tonumber(ARGV[5]) or 1

-- 1. Fetch counts
local prev_val = redis.call("GET", prev_key)
local curr_val = redis.call("GET", current_key)

local prev_count = tonumber(prev_val) or 0
local curr_count = tonumber(curr_val) or 0

local estimated_count = (prev_count * weight_prev) + curr_count

local allowed = 0
if consume > 0 then
    -- Check if request fits under limit
    if estimated_count < limit then
        curr_count = redis.call("INCR", current_key)
        redis.call("EXPIRE", current_key, ttl)
        allowed = 1
        estimated_count = (prev_count * weight_prev) + curr_count
    else
        allowed = 0
    end
else
    allowed = 1
end

local remaining = math.max(0, math.floor(limit - estimated_count))

-- Compute retry_after
local retry_after = 0
if allowed == 0 or remaining == 0 then
    local elapsed_in_window = (1.0 - weight_prev) * window_seconds
    retry_after = math.max(1, math.ceil(window_seconds - elapsed_in_window))
end

-- Return: [allowed (1 or 0), remaining_quota, retry_after_seconds, math.floor(estimated_count)]
return {allowed, remaining, retry_after, math.floor(estimated_count)}

