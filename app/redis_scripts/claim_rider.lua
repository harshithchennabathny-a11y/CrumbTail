-- claim_rider.lua
-- Atomically claims a chosen candidate rider if and only if they are still free.
-- KEYS[1] = riders:geo
-- KEYS[2] = order:{orderId}
-- ARGV[1] = target_rider_id
-- ARGV[2] = order_id
-- ARGV[3] = timestamp

local target_rider_id = ARGV[1]
local order_id = ARGV[2]
local ts = ARGV[3]

local rider_key = 'rider:' .. target_rider_id .. ':latest'
local status = redis.call('HGET', rider_key, 'status') or 'free'

if status == 'free' then
    -- Lock rider to busy
    redis.call('HSET', rider_key, 'status', 'busy', 'active_order_id', order_id, 'assigned_at', ts)
    -- Remove from available geospatial index
    redis.call('ZREM', KEYS[1], target_rider_id)
    -- Bind order cache
    redis.call('HSET', KEYS[2], 'rider_id', target_rider_id, 'status', 'accepted', 'updated_at', ts)
    return target_rider_id
else
    return nil
end

