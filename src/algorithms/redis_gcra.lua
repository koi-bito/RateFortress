-- Atomic GCRA (Generic Cell Rate Algorithm) Rate Limiter
-- KEYS[1] = rate limiter key (e.g., "gcra:{namespace}:{user_id}")
-- ARGV[1] = emission_interval (T = period / limit in seconds)
-- ARGV[2] = burst_tolerance (tau = T * (limit - 1) in seconds)
-- ARGV[3] = now (current Unix epoch timestamp in seconds)
-- ARGV[4] = cost (tokens/cells requested; 0 = inspect only)
-- ARGV[5] = limit (nominal limit)

local key = KEYS[1]
local emission_interval = tonumber(ARGV[1])
local burst_tolerance = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4]) or 1
local limit = tonumber(ARGV[5]) or 10

local burst_horizon = burst_tolerance + emission_interval

local raw_tat = redis.call("GET", key)
local current_tat = raw_tat and tonumber(raw_tat) or 0

if current_tat < now then
    current_tat = now
end

local allowed = 0
local new_tat = current_tat
local retry_after = 0

if cost == 0 then
    -- Read-only inspection
    allowed = 1
    local test_tat = current_tat + emission_interval
    if test_tat - now > burst_horizon then
        retry_after = math.max(1, math.ceil((test_tat - now) - burst_horizon))
    end
else
    local increment = cost * emission_interval
    local proposed_tat = current_tat + increment

    if proposed_tat - now <= burst_horizon then
        allowed = 1
        new_tat = proposed_tat
        redis.call("SET", key, tostring(new_tat))
        local ttl = math.max(60, math.ceil((new_tat - now) + (emission_interval * 2)))
        redis.call("EXPIRE", key, ttl)
    else
        allowed = 0
        local delay = (proposed_tat - now) - burst_horizon
        retry_after = math.max(1, math.ceil(delay))
    end
end

-- Compute remaining quota
local remaining = 0
if not raw_tat or current_tat <= now then
    remaining = limit
else
    local rem = math.floor((now + burst_horizon - new_tat) / emission_interval)
    remaining = math.max(0, math.min(limit, rem))
end

-- Return: [allowed (1 or 0), remaining_quota, retry_after_seconds]
return {allowed, remaining, retry_after}
