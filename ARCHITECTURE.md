# Crumb Tail — Architecture & Distributed Systems Design

**Yuktik 26 Hackathon Challenge**  
*Real-Time Delivery Tracking on Redis with Zero Polling & High Resilience*

---

## 1. High-Level Architecture Topology

```
                         [ Customer Browser ]         [ Kitchen Manager ]         [ Operations Radar ]
                         (/static/index.html)        (/static/restaurant.html)      (/static/ops.html)
                                   \                            |                           /
                                    \                           |                          /
                                     \                          |                         /
                                  WebSocket /ws/orders    WebSocket /ws/restaurant   WebSocket /ws/ops
                                      (Dual-Instance Resilient Failover Client: ws.js)
                                     /                                               \
                                    / < 500ms Instant Reconnect                       \
                                   v                                                   v
                     +----------------------------+                     +----------------------------+
                     |    FastAPI Instance A      |                     |    FastAPI Instance B      |
                     |       (Port 8000)          |                     |       (Port 8001)          |
                     |  Stateless Coordination    |                     |  Stateless Coordination    |
                     +----------------------------+                     +----------------------------+
                                   \                                                   /
                                    +---------------------+---------------------------+
                                                          |
                                      +-------------------+-------------------+
                                      |                                       |
                                      v                                       v
                     +----------------------------------+   +----------------------------------+
                     |             REDIS 7              |   |          SQLITE (WAL)            |
                     |         (Ephemeral Tier)         |   |      (Authoritative Source)      |
                     +----------------------------------+   +----------------------------------+
                     | 1. Geospatial Index (GEOSEARCH): |   | 1. orders:                       |
                     |    riders:geo                    |   |    id, customer_id, rider_id,    |
                     | 2. Atomic Lua State Locks:       |   |    status, created_at, updated_at|
                     |    assign_rider.lua              |   | 2. outbox (Transactional Outbox):|
                     |    assign_batch.lua              |   |    id, event_key, payload, state |
                     |    ingest_location.lua           |   | 3. processed_notifications:      |
                     | 3. Pub/Sub Channels:             |   |    event_key (Idempotent ledger) |
                     |    track:{orderId}, board:orders |   | 4. location_history:             |
                     | 4. Streams (XRANGE Replay):      |   |    Downsampled (<50 writes/sec)  |
                     |    stream:order:{orderId}        |   | 5. idempotency_keys:             |
                     | 5. Sliding-Window Counter:       |   |    HTTP 429 & Request dedup      |
                     |    device:{id}:pings             |   +----------------------------------+
                     +----------------------------------+                     |
                                                                              v
                                                            +----------------------------------+
                                                            |      Outbox Worker Daemon        |
                                                            |  Backoff + Random Jitter (1.5^n) |
                                                            +----------------------------------+
                                                                              |
                                                                 HTTP POST /notify (Port 9000)
                                                                              v
                                                            +----------------------------------+
                                                            |   Mock Notification Service      |
                                                            |    Idempotent Event Ledger       |
                                                            +----------------------------------+
```

---

## 2. Distributed Guarantees & Implementation Contracts

### A. Zero Double-Bookings under Concurrency (Nearest Rider Assignment)
- **Problem**: When 20 orders burst in at the exact same millisecond near Koramangala, competing threads could assign the same rider.
- **Solution**: Executed in a single atomic Redis Lua script (`app/redis_scripts/assign_rider.lua`):
  1. `GEOSEARCH riders:geo FROMLONLAT lon lat BYRADIUS radius_km ASC WITHDIST`
  2. Evaluates first candidate rider whose Redis hash `rider:{id}:latest` has `status == 'free'`.
  3. Atomically sets `status = 'busy'`, records `active_order_id`, and removes rider from `riders:geo`.
  4. Redis single-threaded execution guarantees strictly **0 race conditions and 0 double bookings**.

### B. Monotonic GPS Ingestion (Marker Never Moves Backward)
- **Problem**: High-speed cellular networks deliver out-of-order, delayed, or duplicate packets, causing map markers to oscillate or jump backward.
- **Solution**: Handled at Redis ingest boundary via `app/redis_scripts/ingest_location.lua`:
  1. Compares incoming `seq` against stored sequence `rider:{id}:seq`.
  2. If `incoming_seq <= stored_seq`, immediately drops the packet (`return -1`).
  3. Only when `incoming_seq > stored_seq`:
     - Updates `rider:{id}:seq` and coordinate hash.
     - Updates `riders:geo` geospatial index.
     - Atomically publishes to Pub/Sub `track:{orderId}`.
     - Appends frame to Redis Stream `stream:order:{orderId}` (`XADD`).

### C. Database Write Throttling (< 50 writes/s under 2,000 Riders)
- **Problem**: 2,000 delivery partners transmitting 1 Hz GPS updates generate 2,000 writes/second. Direct database writes would exhaust SQLite disk I/O.
- **Solution**: In-memory downsampling buffer (`app/location_sampler.py`):
  1. Incoming 1 Hz updates are absorbed by Redis in memory.
  2. In-memory sampler persists only 1 point per 60 seconds per active rider to SQLite `location_history`.
  3. Flushed in transactions of 50 items.
  4. Formula: $\frac{2000 \text{ riders}}{60 \text{ seconds}} = 33.3 \text{ writes/second}$, strictly below the **50 writes/sec** threshold.

### D. Instant Dual-Instance Failover (< 500 ms) with Stream Replay
- **Problem**: If Instance A (port 8000) crashes, connected customers lose live telemetry.
- **Solution**:
  1. Resilient client (`static/js/ws.js`) maintains endpoint list `[ws://localhost:8000, ws://localhost:8001]`.
  2. When socket disconnects, switches port within **50 ms** without page reload.
  3. Reconnected socket immediately sends handshake:
     `{ "action": "hello", "last_event_id": "<last_stream_id>" }`
  4. Instance B queries `XRANGE stream:order:{id} (<last_stream_id> +` and streams any missed location frames to the client before switching to live Pub/Sub.

### E. Transactional Outbox & Notification Idempotency
- **Problem**: Dual-write hazard between SQLite order state and remote HTTP notification services.
- **Solution**:
  1. Order status change and outbox message insertion (`event_key = orderId:status`) execute in **1 single atomic SQLite transaction**.
  2. Background daemon (`app/outbox_worker.py`) polls pending outbox entries.
  3. Dispatches to standalone notification service (`http://localhost:9000/notify`) with exponential backoff ($1.5^n$) and randomized jitter.
  4. Notification service maintains persistent `processed_notifications` ledger: repeated dispatches return `HTTP 200 already_processed`, guaranteeing **strictly 0 duplicate alerts**.

