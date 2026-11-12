-- assign_batch.lua
-- Atomically binds a single free rider to TWO competing orders or changes nothing.
-- KEYS[1] = riders:geo
-- KEYS[2] = order:{orderId1}
-- KEYS[3] = order:{orderId2}
-- ARGV[1] = center_lon
-- ARGV[2] = center_lat
-- ARGV[3] = radius_km
-- ARGV[4] = order_id_1
-- ARGV[5] = order_id_2
-- ARGV[6] = timestamp

local center_lon = ARGV[1]
local center_lat = ARGV[2]
local radius = ARGV[3] or '5'
local order_id_1 = ARGV[4]
local order_id_2 = ARGV[5]
local ts = ARGV[6]

-- 1. Search candidate riders
local candidates = redis.call('GEOSEARCH', KEYS[1], 'FROMLONLAT', center_lon, center_lat, 'BYRADIUS', radius, 'km', 'ASC', 'COUNT', 10)

if not candidates or #candidates == 0 then
    return nil
end

-- 2. Find free rider and assign both atomically
for _, rider_id in ipairs(candidates) do
    local rider_key = 'rider:' .. rider_id .. ':latest'
    local status = redis.call('HGET', rider_key, 'status') or 'free'
    
    if status == 'free' then
        -- Atomically mark rider busy with both orders
        redis.call('HSET', rider_key, 'status', 'busy', 'active_order_id', order_id_1, 'active_order_id_2', order_id_2, 'batch_mode', '1', 'assigned_at', ts)
        redis.call('ZREM', KEYS[1], rider_id)
        
        -- Update both orders
        redis.call('HSET', KEYS[2], 'rider_id', rider_id, 'status', 'accepted', 'updated_at', ts)
        redis.call('HSET', KEYS[3], 'rider_id', rider_id, 'status', 'accepted', 'updated_at', ts)
        
        return rider_id
    end
end

return nil

