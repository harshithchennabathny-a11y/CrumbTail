# Requirements & Verification Matrix — Crumb Tail

## 1. Functional Requirements

### 1.1 Order Management & Lifecycle (State Machine)
- **REQ-ORD-1**: Customer can place an order via `POST /orders`, initialized to status `placed`.
- **REQ-ORD-2**: State machine moves strictly through `placed` -> `accepted` -> `preparing` -> `picked_up` -> `delivered`, with `cancelled` allowed from `placed`, `accepted`, or `preparing`.
- **REQ-ORD-3**: Any request attempting to skip a state or move backwards must return `HTTP 409 Conflict`.
- **REQ-ORD-4**: All mutating requests must accept and enforce an `idempotency_key`.

### 1.2 Rider Geospatial Index & Assignment
- **REQ-RDR-1**: Maintain available riders in Redis geospatial index (`GEOADD riders:geo lon lat riderId`).
- **REQ-RDR-2**: When an order is moved to `accepted`, system automatically runs `GEOSEARCH` within a radius, sorted by distance.
- **REQ-RDR-3**: Rider assignment must be executed using an atomic Redis Lua script.
  - Script checks if rider is free, marks busy, attaches to order, and removes from `riders:geo`.
  - Guarantees zero double assignments when Instance A and B attempt simultaneous assignment.
  - Batch assignment: if assigning 2 orders to 1 rider, checks both orders and assigns both or changes nothing.

### 1.3 Location Ingestion & Deduplication
- **REQ-LOC-1**: Ingest rider GPS packets via `POST /locations` containing `{rider_id, lat, lon, seq, timestamp}`.
- **REQ-LOC-2**: An atomic Lua script checks `seq`. If `seq <= stored_seq`, the packet is dropped as duplicate/stale.
- **REQ-LOC-3**: Accepted points update rider coordinate in Redis, refresh the geo set (if available), and publish to `track:{orderId}` channels for active orders.
- **REQ-LOC-4**: Frontend client refuses any packet with `seq <= last_rendered_seq`, ensuring markers never move backwards.

### 1.4 Real-Time WebSockets & Targeted Fan-Out
- **REQ-WS-1**: Customers, restaurant staff, and ops connect via WebSocket (`/ws/orders/{orderId}`, `/ws/ops`, `/ws/restaurant`).
- **REQ-WS-2**: Targeted Pub/Sub: App instance subscribes to Redis channel `track:{orderId}` only when local client connects, and unsubscribes when last viewer disconnects.
- **REQ-WS-3**: Reconnection & Missed Event Catch-Up: On WebSocket connect, client sends `hello` with last seen event ID. Server replays missed events from a Redis stream and transitions to live push.

### 1.5 Transactional Outbox & Reliable Notifications
- **REQ-NOTIF-1**: Order status changes write both the updated order state and an outbox row (`orderId`, `status`, `event_key`, `payload`, `status='pending'`) inside a single database transaction.
- **REQ-NOTIF-2**: Background outbox worker queries pending events, dispatches to notification service, and marks them `sent`.
- **REQ-NOTIF-3**: If notification service is down, worker retries with exponential backoff and randomized jitter.
- **REQ-NOTIF-4**: Notification service enforces idempotency using `orderId:status`, ensuring exactly-once notification delivery.

### 1.6 Database Persistence & Write Throttling
- **REQ-DB-1**: Live GPS updates are stored purely in Redis.
- **REQ-DB-2**: At 2,000 riders, database writes must remain $< 50$ writes/sec. Locations are sampled at 1 point/min per active rider and bulk-inserted in batches.

### 1.7 Rate Limiting
- **REQ-RL-1**: Sliding-window rate limiter implemented in Redis Lua to prevent device flooding and customer action spam across both instances.

---

## 2. Non-Functional & Resilience Requirements

### 2.1 Multi-Instance & Failover
- **REQ-RES-1**: App runs on at least 2 identical FastAPI instances (Instance A on port 8000, Instance B on port 8001).
- **REQ-RES-2**: When one instance terminates abruptly, clients reconnect to the surviving instance within 500 ms and catch up missed events in $< 5$ seconds.
- **REQ-RES-3**: When Redis restarts, relational database preserves order state; system enters degraded mode with UI warning banner, and repopulates GPS coordinates upon rider pings.

### 2.2 Live Dashboards & Simulation Tools
- **REQ-DASH-1**: Customer Tracking Page showing live map with smooth interpolation, ETA/distance remaining, and status timeline.
- **REQ-DASH-2**: Restaurant Order Board with optimistic drag-and-drop state transitions (with rollback on HTTP 409).
- **REQ-DASH-3**: Operations Map & Dashboard showing all active riders, updates/sec, latency, viewer count, DB writes/s, and pending outbox notifications.
- **REQ-DASH-4**: Chaos Control Panel with test trigger buttons:
  - Send bad location data (duplicates, stale seq).
  - Burst order placement with limited riders.
  - Competing batch assignments.
  - Notification service kill & restore.
  - Instance A/B kill & revive.
  - Redis connection interruption.
- **REQ-SIM-1**: Fleet simulator capable of simulating up to 2,000 riders transmitting at 1 Hz along realistic paths.
- **REQ-SIM-2 (Massive Scale & Stress Validation)**: High-volume test harness generating **1,000+ test scenarios and stress cases** (burst orders, competing assignments, GPS jitter, network drops, packet reordering) to demonstrate system stability and output a comprehensive statistical benchmark scorecard (p50, p95, p99 latencies, 0 double assignments, 0 backward jumps). *To be executed after core platform build.*

