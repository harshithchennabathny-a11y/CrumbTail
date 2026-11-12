# Crumb Trail Technical Specification (SPEC.md)
Yuktik 26 · Real-Time Delivery Tracking on Redis

This document defines the formal engineering contract: authoritative data ownership, SQLite WAL concurrency, Redis key schemas, atomic Lua script contracts, race-free WebSocket replay protocols, and distributed presence semantics.

---

## 1. System Topology & Dual Stateless Instances

- **Instance A**: `http://localhost:8000` (FastAPI / Uvicorn, binds to `0.0.0.0`)
- **Instance B**: `http://localhost:8001` (FastAPI / Uvicorn, binds to `0.0.0.0`)
- **Shared Infrastructure**:
  - Redis 7.2.5 on `localhost:6379`
  - SQLite 3 on `crumb_trail.db` (configured in WAL mode)
- **Authoritative Ownership Rule**:
  - **SQLite is Authoritative** for all durable business state (Orders, Order Lifecycle History, and Transactional Outbox).
  - **Redis is Authoritative** for all ephemeral real-time state (Live GPS Coordinates, Active Geo Search Index, Rate Limiter Windows, and Ephemeral Viewer Presence).

---

## 2. SQLite Database Configuration & Schema (WAL Concurrency)

### 2.1 Concurrency Pragma Configuration
Every connection to SQLite must execute:
```sql
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
```
All state-modifying operations must use `BEGIN IMMEDIATE` transactions to prevent write deadlocks between Instance A and Instance B.

### 2.2 Tables Schema
```sql
-- Orders Table (Authoritative Durable Order State)
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    restaurant_id TEXT NOT NULL,
    rider_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('placed', 'accepted', 'preparing', 'picked_up', 'delivered', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transactional Outbox Table (At-Least-Once Dispatch)
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE NOT NULL, -- Format: {orderId}:{status}
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'sent', 'failed')),
    retry_count INTEGER DEFAULT 0,
    next_retry_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

-- Consumer Processed Ledger (Guarantees Idempotent Consumption)
CREATE TABLE IF NOT EXISTS processed_notifications (
    event_key TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    status TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Order Lifecycle Audit History
CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sampled Batched Location History (< 50 writes/s under 2,000 riders)
CREATE TABLE IF NOT EXISTS location_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rider_id TEXT NOT NULL,
    order_id TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    seq INTEGER NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Redis Key Schemas & Distributed Presence

| Key Pattern | Redis Type | Authoritative Function / Expiry |
| :--- | :--- | :--- |
| `riders:geo` | Sorted Set (GEO) | Available riders index (`lon`, `lat`, `riderId`). Removed upon assignment. |
| `rider:{riderId}:latest` | Hash | `{lat, lon, seq, status, active_order_id, updated_at}`. |
| `rider:{riderId}:seq` | Integer (String) | Highest accepted monotonic sequence number. |
| `order:{orderId}` | Hash | Ephemeral hot read-cache of order `{id, status, rider_id}`. Rebuildable from SQLite. |
| `track:{orderId}` | Pub/Sub Channel | Real-time broadcast channel for live coordinates: `{lat, lon, seq, ts, stream_id}`. |
| `stream:order:{orderId}` | Redis Stream | Durable order event stream (`MAXLEN ~ 1000`). Written atomically with Pub/Sub. |
| `presence:order:{orderId}` | Hash | Distributed presence leases: field `<instance_id>:<connection_id>`, value `<heartbeat_ts>`. Leases expired after 10s. |
| `ratelimit:{device_id}` | Sorted Set (ZSET)| Sliding-window timestamp counter (60s window). |

---

## 4. Atomic Redis Lua Script Contracts

### 4.1 Ingestion Script: `ingest_location.lua`
**CRITICAL INVARIANT**: Coordinates MUST be appended to Redis Stream (`XADD`) and broadcast (`PUBLISH`) **atomically in the same Lua execution** to eliminate the replay race condition.

```lua
-- KEYS[1] = rider:{id}:seq
-- KEYS[2] = rider:{id}:latest
-- KEYS[3] = riders:geo
-- KEYS[4] = stream:order:{orderId} (or empty if no active order)
-- KEYS[5] = channel track:{orderId}
-- ARGV[1] = rider_id
-- ARGV[2] = incoming_seq (number)
-- ARGV[3] = lat (number)
-- ARGV[4] = lon (number)
-- ARGV[5] = timestamp (number)
-- ARGV[6] = active_order_id (string or "")

local current_seq = tonumber(redis.call('GET', KEYS[1]) or '-1')
local incoming_seq = tonumber(ARGV[2])

if incoming_seq <= current_seq then
    return 0 -- Stale or duplicate packet: DROPPED
end

-- 1. Update monotonic sequence and latest hash
redis.call('SET', KEYS[1], incoming_seq)
redis.call('HSET', KEYS[2], 'lat', ARGV[3], 'lon', ARGV[4], 'seq', incoming_seq, 'updated_at', ARGV[5])

-- 2. If rider is free, update geo set
local rider_status = redis.call('HGET', KEYS[2], 'status') or 'free'
if rider_status == 'free' then
    redis.call('GEOADD', KEYS[3], ARGV[4], ARGV[3], ARGV[1])
end

-- 3. If active order exists, append to Stream AND Publish atomically
if ARGV[6] ~= "" and KEYS[4] ~= "" then
    local stream_id = redis.call('XADD', KEYS[4], '*', 'type', 'location', 'rider_id', ARGV[1], 'lat', ARGV[3], 'lon', ARGV[4], 'seq', incoming_seq, 'ts', ARGV[5])
    local payload = cjson.encode({
        type = 'location',
        stream_id = stream_id,
        rider_id = ARGV[1],
        lat = tonumber(ARGV[3]),
        lon = tonumber(ARGV[4]),
        seq = incoming_seq,
        ts = tonumber(ARGV[5])
    })
    redis.call('PUBLISH', KEYS[5], payload)
end

return 1 -- Packet ACCEPTED
```

### 4.2 Assignment Script: `assign_rider.lua`
```lua
-- KEYS[1] = riders:geo
-- KEYS[2] = order:{orderId}
-- ARGV[1] = center_lon
-- ARGV[2] = center_lat
-- ARGV[3] = radius_km (default 5)
-- ARGV[4] = order_id
-- ARGV[5] = timestamp

local candidates = redis.call('GEOSEARCH', KEYS[1], 'FROMLONLAT', ARGV[1], ARGV[2], 'BYRADIUS', ARGV[3], 'km', 'ASC', 'COUNT', 5)

for _, rider_id in ipairs(candidates) do
    local rider_key = 'rider:' .. rider_id .. ':latest'
    local status = redis.call('HGET', rider_key, 'status') or 'free'
    if status == 'free' then
        -- Atomically lock rider
        redis.call('HSET', rider_key, 'status', 'busy', 'active_order_id', ARGV[4])
        redis.call('ZREM', KEYS[1], rider_id) -- Remove from geo availability
        redis.call('HSET', KEYS[2], 'rider_id', rider_id, 'assigned_at', ARGV[5])
        return rider_id -- Assignment SUCCESS
    end
end

return nil -- No candidate available
```

---

## 5. Race-Free WebSocket Replay Protocol (High-Watermark Synchronization)

To prevent dropped messages when reconnecting:
1. **Step 1 (Subscribe)**: Server subscribes client connection to Redis Pub/Sub channel `track:{orderId}`.
2. **Step 2 (Buffer)**: Server buffers any live incoming Pub/Sub frames in memory for this connection.
3. **Step 3 (High-Watermark)**: Server inspects the current latest Redis Stream ID (`XREVRANGE stream:order:{orderId} + - COUNT 1`).
4. **Step 4 (Replay)**: Server replays all missed events from `last_event_id` up to the high-watermark.
5. **Step 5 (Drain Buffer with Deduplication)**: Server flushes buffered live frames, dropping any frame whose `stream_id` or `seq` was already delivered during Step 4.
6. **Step 6 (Live Push)**: Server transitions to direct unbuffered live push.

---

## 6. Distributed Presence Leases (`presence:order:{orderId}`)

- Instances report viewer heartbeats to Redis:
  `HSET presence:order:{orderId} <instance_id>:<conn_id> <current_unix_ts>`
- When WebSocket closes:
  `HDEL presence:order:{orderId} <instance_id>:<conn_id>`
- Viewer count query:
  Scans fields and counts leases where `(current_unix_ts - heartbeat_ts) < 10` seconds. Leases older than 10s are pruned.

---

## 7. Dual-Endpoint Failover Architecture

Frontends are initialized with dual failover targets:
```javascript
const INSTANCES = ['http://localhost:8000', 'http://localhost:8001'];
```
- If Instance A terminates, client detects disconnect, tries Instance B within 250ms, sends `hello` with `last_event_id`, and resumes live tracking in $< 500$ ms.

---

## 8. Live System Event Timeline Specification

Every backend action emits an observable event to a Redis Pub/Sub channel `system:timeline`.
Format:
```json
{
  "timestamp": "2026-11-13T00:55:01.102Z",
  "instance": "Instance_A",
  "category": "ASSIGNMENT",
  "event": "Rider r_42 assigned to order ord_8891 (latency: 12ms)",
  "metadata": { "order_id": "ord_8891", "rider_id": "r_42", "duration_ms": 12 }
}
```
All frontend dashboards include a live scrolling terminal displaying this timeline so judges can observe operations in real time.
