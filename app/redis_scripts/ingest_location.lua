-- ingest_location.lua
-- Monotonic sequence verification, coordinate update, atomic Stream append & Pub/Sub publish
-- KEYS[1] = rider:{id}:seq
-- KEYS[2] = rider:{id}:latest
-- KEYS[3] = riders:geo
-- ARGV[1] = rider_id
-- ARGV[2] = incoming_seq (number)
-- ARGV[3] = lat (number)
-- ARGV[4] = lon (number)
-- ARGV[5] = timestamp (number)

local rider_id = ARGV[1]
local incoming_seq = tonumber(ARGV[2])
local lat = ARGV[3]
local lon = ARGV[4]
local ts = ARGV[5]

-- 1. Compare incoming sequence against stored monotonic counter
local current_seq = tonumber(redis.call('GET', KEYS[1]) or '-1')

if incoming_seq <= current_seq then
    -- Duplicate or out-of-order stale packet: REJECT
    return 0
end

-- 2. Update sequence counter and latest coordinate hash
redis.call('SET', KEYS[1], incoming_seq)
redis.call('HSET', KEYS[2], 'lat', lat, 'lon', lon, 'seq', incoming_seq, 'updated_at', ts)

-- 3. If rider is available/free, keep geo search index updated
local rider_status = redis.call('HGET', KEYS[2], 'status') or 'free'
if rider_status == 'free' then
    redis.call('GEOADD', KEYS[3], lon, lat, rider_id)
end

-- 4. Check if rider is assigned to an active order
local active_order = redis.call('HGET', KEYS[2], 'active_order_id') or ''
if active_order ~= '' then
    local stream_key = 'stream:order:' .. active_order
    local channel_key = 'track:' .. active_order
    
    -- Append to durable stream for reconnect replay
    local stream_id = redis.call('XADD', stream_key, '*',
        'type', 'location',
        'rider_id', rider_id,
        'lat', lat,
        'lon', lon,
        'seq', incoming_seq,
        'timestamp', ts
    )
    
    -- Atomically publish to active order channel
    local payload = cjson.encode({
        type = 'location',
        order_id = active_order,
        rider_id = rider_id,
        lat = tonumber(lat),
        lon = tonumber(lon),
        seq = incoming_seq,
        timestamp = tonumber(ts),
        stream_id = stream_id
    })
    redis.call('PUBLISH', channel_key, payload)
end

-- Also check if rider has a second order in batch mode
local active_order_2 = redis.call('HGET', KEYS[2], 'active_order_id_2') or ''
if active_order_2 ~= '' then
    local stream_key2 = 'stream:order:' .. active_order_2
    local channel_key2 = 'track:' .. active_order_2
    
    local stream_id2 = redis.call('XADD', stream_key2, '*',
        'type', 'location',
        'rider_id', rider_id,
        'lat', lat,
        'lon', lon,
        'seq', incoming_seq,
        'timestamp', ts
    )
    local payload2 = cjson.encode({
        type = 'location',
        order_id = active_order_2,
        rider_id = rider_id,
        lat = tonumber(lat),
        lon = tonumber(lon),
        seq = incoming_seq,
        timestamp = tonumber(ts),
        stream_id = stream_id2
    })
    redis.call('PUBLISH', channel_key2, payload2)
end

return 1 -- Packet ACCEPTED

