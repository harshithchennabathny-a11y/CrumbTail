-- assign_rider.lua
-- Atomically selects nearest available rider and binds them to the order.
-- KEYS[1] = riders:geo
-- KEYS[2] = order:{orderId}
-- ARGV[1] = center_lon
-- ARGV[2] = center_lat
-- ARGV[3] = radius_km (e.g. 5)
-- ARGV[4] = order_id
-- ARGV[5] = timestamp

local center_lon = ARGV[1]
local center_lat = ARGV[2]
local radius = ARGV[3] or '5'
local order_id = ARGV[4]
local ts = ARGV[5]

-- 1. Search for nearest candidate riders sorted by ascending distance
local candidates = redis.call('GEOSEARCH', KEYS[1], 'FROMLONLAT', center_lon, center_lat, 'BYRADIUS', radius, 'km', 'ASC', 'COUNT', 10)

if not candidates or #candidates == 0 then
    return nil
end

-- 2. Inspect candidates and claim the first free rider atomically
for _, rider_id in ipairs(candidates) do
    local rider_key = 'rider:' .. rider_id .. ':latest'
    local status = redis.call('HGET', rider_key, 'status') or 'free'
    
    if status == 'free' then
        -- Ghost rider gate: check if rider has become stale (no pings in > 300s)
        local last_update = tonumber(redis.call('HGET', rider_key, 'updated_at') or '0')
        local current_time = tonumber(ts) or 0
        if last_update > 0 and current_time > 0 and (current_time - last_update > 300) then
            -- Purge stale ghost rider from search index
            redis.call('ZREM', KEYS[1], rider_id)
            redis.call('HSET', rider_key, 'status', 'offline')
        else
            -- Lock rider to busy
            redis.call('HSET', rider_key, 'status', 'busy', 'active_order_id', order_id, 'assigned_at', ts)
            -- Remove from available geospatial index
            redis.call('ZREM', KEYS[1], rider_id)
            -- Bind order cache
            redis.call('HSET', KEYS[2], 'rider_id', rider_id, 'status', 'accepted', 'updated_at', ts)
            
            return rider_id
        end
    end
end

return nil

