# Crumb Trail — Hackathon Execution Blueprint (Yuktik 26)

You can copy the entire prompt below and use it to direct the autonomous execution of the platform.

***

```markdown
You are a pragmatic systems engineer building **Crumb Trail**, a real-time delivery tracking platform on Redis and FastAPI for the Yuktik 26 hackathon.

### Core Philosophy: Hackathon-Winning & Observability
Marks go ONLY to behaviors judges can see and test live. Do not over-engineer with enterprise bloat. Keep code clean, modular, and built phase-by-phase so that every subsystem is runnable and verified immediately.

---

### Key Requirements Verified by Judges
1. **Zero HTTP Polling**: 100% WebSocket push (DevTools Network tab shows 0 polling requests).
2. **Atomic Single & Batch Assignment**: 0 double-bookings. Supports competing batches (assigns both orders or changes nothing via `assign_batch.lua`).
3. **Monotonic GPS Coordinates**: Stale/duplicate packets (`seq <= stored_seq`) are rejected by Redis; markers never move backward.
4. **Real Notification Service on Port 9000**: A real standalone process (`app/mock_notification_service.py`) that logs received keys. Survives shutdown and restart without losing or duplicating alerts.
5. **Real Redis Disconnect Resilience**: Real `redis.ConnectionError` handling. When Redis is stopped, app returns degraded mode, and auto-reconnects when Redis restarts.
6. **Dual-Instance Client Failover**: `ws.js` knows `['http://localhost:8000', 'http://localhost:8001']`. When Instance A is killed, it reconnects to Instance B in < 500 ms without page reload.
7. **Database Write Throttling**: 2,000 riders sending 1 Hz pings are buffered in Redis; sampled to SQLite once a minute (< 50 writes/s).
8. **Real Measurements Only**: No hardcoded metrics or fake timers. All latencies, DB write counts, and benchmark numbers are measured live.

---

### Build in 4 Phased Milestones (Never Build All at Once)

#### Phase 1: Storage, Contract & Dual FastAPI Instances
1. Create `app/database.py` with SQLite WAL mode (`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`).
2. Create SQLite tables: `orders`, `outbox`, `order_events`, `location_history`, `idempotency_keys`.
3. Create `app/redis_client.py` connecting to Redis on `localhost:6379` (installed in `tools/redis/redis-server.exe`) with auto-reconnect and degraded mode detection.
4. Create dual FastAPI instances: `app/main_a.py` (port 8000) and `app/main_b.py` (port 8001), both mounting `/static` and binding to `0.0.0.0`.
5. Implement `/health` endpoint returning `{ "status": "healthy"|"degraded", "instance": "A"|"B", "redis": true, "database": true }`.
* **Phase 1 Verification Gate**: Run `scripts/init_db.py`, start both instances, verify `GET http://localhost:8000/health` and `http://localhost:8001/health` both return healthy.

#### Phase 2: Order State Machine, Outbox & Atomic Lua Engine
1. Implement `POST /orders` (idempotent via `X-Idempotency-Key` or SQLite table).
2. Implement `POST /orders/{id}/status`:
   - Validates state transitions (`placed` -> `accepted` -> `preparing` -> `picked_up` -> `delivered`, `cancelled`).
   - Rejects illegal transitions with `HTTP 409 Conflict`.
   - In single SQLite transaction: updates order status AND inserts outbox row (`orderId:status`).
3. Create `app/redis_scripts/assign_rider.lua`:
   - Performs `GEOSEARCH riders:geo`, checks if rider is free, marks busy, stores `active_order_id`, and removes from geo set.
4. Create `app/redis_scripts/assign_batch.lua`:
   - Takes rider ID and 2 order IDs. Verifies rider is free, then atomically assigns both orders or changes nothing.
5. Create `app/mock_notification_service.py` (runs on port 9000):
   - Receives `POST /notify`, checks persistent `processed_keys` set, logs received alerts, returns 200.
6. Create `app/outbox_worker.py`:
   - Single daemon polling `outbox WHERE state='pending'`, sends to `http://localhost:9000/notify`, retries with backoff and jitter.
* **Phase 2 Verification Gate**: Run `pytest tests/test_state_machine.py tests/test_atomic_assignment.py` (verifies 0 double bookings under race condition).

#### Phase 3: Location Ingestion, WebSockets & Reconnect Replay
1. Create `app/redis_scripts/ingest_location.lua`:
   - Compares incoming `seq` against `rider:{id}:seq`. If `seq <= stored_seq`, drops packet (returns 0).
   - If valid, updates coordinate hash. Reads `active_order_id`. If assigned, calls `XADD stream:order:{orderId}` AND `PUBLISH track:{orderId}`.
2. Implement `POST /locations` endpoint (calls `ingest_location.lua`).
3. Implement `app/websockets.py`:
   - `/ws/orders/{orderId}`: On connect, client sends `hello` with `last_event_id`. Server queries Redis Stream for missed events, replays them, then subscribes to `track:{orderId}`.
   - `/ws/ops`: Pushes live fleet stats and metrics.
   - Dynamic Pub/Sub: Instance subscribes only when an active local viewer exists.
4. Implement background DB batch sampler:
   - Samples 1 location per minute per active rider and bulk-inserts to `location_history` (< 50 writes/s).
* **Phase 3 Verification Gate**: Run `pytest tests/test_monotonic_seq.py tests/test_outbox_and_streams.py`.

#### Phase 4: Interactive Frontend Testbed, Simulators & Chaos Engine
1. **Customer Live Tracking (`static/index.html` + `static/js/tracker.js`)**:
   - One-click "Place Sample Order" button.
   - Leaflet map with smooth `requestAnimationFrame` lerp interpolation. Drops backward packets.
   - "Disconnect WS" / "Reconnect WS" buttons proving event replay from Redis Stream without page reload.
2. **Restaurant Order Board (`static/restaurant.html` + `static/js/board.js`)**:
   - 5-column Kanban board with HTML5 drag-and-drop.
   - Moving card to `Accepted` triggers assignment and displays rider ID.
   - Dragging illegally (e.g. `Placed` -> `Delivered`) triggers `HTTP 409 Conflict` toast and card snaps back.
3. **Operations Live Map (`static/ops.html` + `static/js/ops.js`)**:
   - High-performance HTML5 `<canvas>` rendering 2,000 rider dots (green = free, orange = delivering) at 60 FPS.
   - Real-time gauges: **Updates/sec**, **Delivery Latency p95 (ms)**, **Active Viewers**, **Database Writes/sec**, **Pending Notifications**.
   - Fleet simulator controls: Slider for 10 to 2,000 riders + Start/Stop buttons.
4. **Chaos Control Panel (`static/chaos.html` + `static/js/chaos.js`)**:
   - 💥 *Inject Bad GPS Data*: Sends duplicate/stale `seq`; proves marker stays still.
   - 💥 *Burst 20 Concurrent Orders*: Hammers assignment; proves 0 double bookings.
   - 💥 *Competing Batch Test*: Proves batch Lua assigns both or none.
   - 💥 *Kill Notification Service*: Stops port 9000; proves outbox rows stay pending.
   - 💥 *Restart Notification Service*: Restarts port 9000; proves outbox drains with 0 duplicates.
   - 💥 *Kill FastAPI Instance A*: Terminates port 8000; proves WebSocket reconnects to port 8001 in < 500 ms.
5. **Fleet Simulator (`simulator/fleet_sim.py`)**:
   - Simulates riders along coordinates in Bengaluru (lat: 12.96-12.98, lon: 77.62-77.65) with modes for clean, noisy, and burst.
6. **1,000-Scenario Benchmark Engine (`scripts/benchmark_1000_scenarios.py`)**:
   - Runs 1,000 real parallel scenarios measuring actual `time.perf_counter()` latencies and real DB rows.
   - Outputs a verified scorecard (p50/p95/p99 latency, 0 double bookings, 0 backward marker jumps, 0 duplicate notifications, DB writes < 50/s).

---

### Startup Scripts to Generate
- `scripts/init_db.py`: Initializes SQLite schema.
- `scripts/run_instance_a.bat`: Starts Instance A on port 8000.
- `scripts/run_instance_b.bat`: Starts Instance B on port 8001.
- `scripts/run_notifications.bat`: Starts Mock Notification Service on port 9000.
- `scripts/start_all.bat`: One-click master startup script for all services.
```

