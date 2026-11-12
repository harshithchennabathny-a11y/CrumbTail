-- rate_limiter.lua
-- Sliding-window rate limiter using Redis Sorted Set (ZSET)
-- KEYS[1] = ratelimit:{identifier}
-- ARGV[1] = current_timestamp_ms (number)
-- ARGV[2] = window_ms (number, e.g. 1000 for 1 sec)
-- ARGV[3] = max_requests (number, e.g. 20)

local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])

local clear_before = now - window

-- 1. Remove expired request timestamps outside the window
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. Count requests in current window
local current_requests = redis.call('ZCARD', key)

if current_requests >= max_requests then
    return 0 -- Rate limit EXCEEDED
end

-- 3. Record new request timestamp with unique member value
redis.call('ZADD', key, now, now .. ':' .. math.random(1, 100000))
-- Set key expiration to window duration
redis.call('PEXPIRE', key, window + 1000)

return 1 -- Request ALLOWED

