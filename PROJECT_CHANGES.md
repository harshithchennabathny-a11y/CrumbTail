# Project Change Log — Crumb Tail (Yuktik 26)

This document records all modifications made to the project across codebase, configuration, schemas, scripts, and documentation whenever prompted.

---

## Change History

### [2026-11-13 01:23] — Phase 3: Location Ingestion, WebSockets & Reconnect Replay Complete
- **Type**: `[FEATURE]` / `[REALTIME]` / `[WEBSOCKETS]` / `[LUA]` / `[TEST]`
- **Trigger**: Execution of Phase 3 milestone.
- **Files Created / Modified**:
  - `app/redis_scripts/ingest_location.lua`: Enforces monotonic sequence counter (`seq <= stored_seq` drops packet), updates coordinate hashes, and atomically appends to Redis Stream (`XADD stream:order:{id}`) and publishes to Pub/Sub (`PUBLISH track:{id}`).
  - `app/redis_scripts/rate_limiter.lua`: Sliding-window rate limiter using Redis sorted sets (ZSET) to throttle device flooding (HTTP 429).
  - `app/location_sampler.py`: Downsamples 1 Hz GPS telemetry to 1 point/minute per active rider and executes bulk-insert transactions to SQLite (`location_history`), maintaining DB writes $< 50$/sec.
  - `app/routers/locations.py`: Implemented `POST /locations` with rate-limiting, stale packet rejection, and rider registration/availability endpoints.
  - `app/websockets.py`: Full WebSocket gateway implementing `/ws/orders/{orderId}` (with `hello` handshake and Redis Stream catch-up replay), `/ws/restaurant` (order board stream), and `/ws/ops` (fleet monitoring stream).
  - `app/main.py`: Mounted locations router and websockets router on both FastAPI instances.
  - `tests/test_monotonic_seq.py`: Verified valid seq ingestion, duplicate seq drop, stale out-of-order seq drop, sliding-window rate limit, and downsampled SQLite batch persistence.
  - `tests/test_websockets_and_replay.py`: Verified WebSocket live location reception, `hello` handshake stream replay, and targeted channel isolation between orders.
- **Verification**:
  - `pytest tests/ -v` passed **23/23 tests (100%)** in 2.51s.

---

### [2026-11-13 01:19] — Phase 2: Order State Machine, Outbox & Atomic Lua Engine Complete
- **Type**: `[FEATURE]` / `[BACKEND]` / `[LUA]` / `[TEST]`
- **Trigger**: Execution of Phase 2 milestone.
- **Files Created / Modified**:
  - `app/models.py`: Pydantic data models for `OrderCreate`, `OrderStatusUpdate`, `OrderResponse`, `BatchAssignRequest`, and `NotificationMessage`.
  - `app/crud.py`: Implemented state machine transitions with `HTTP 409 Conflict` checks, atomic SQLite writes (order status + outbox row + event log), and idempotency ledger operations.
  - `app/redis_scripts/assign_rider.lua`: Atomic `GEOSEARCH` + availability verification + busy state lock + removal from `riders:geo`.
  - `app/redis_scripts/assign_batch.lua`: Atomic dual-order batch assignment (assigns both or changes nothing).
  - `app/redis_client.py`: Script loader and execution bindings for atomic assignment scripts.
  - `app/routers/orders.py`: Endpoints for `POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/status`, and `POST /orders/batch-assign`.
  - `app/mock_notification_service.py`: Standalone notification service on port 9000 with persistent idempotency ledger.
  - `app/outbox_worker.py`: Background worker polling pending outbox events with exponential backoff and randomized jitter.
  - `scripts/run_notifications.bat`: Process launcher for the port 9000 notification service.
  - `tests/test_state_machine.py`: 6 tests verifying order progression, 409 rollbacks, cancellation rules, and idempotency deduplication.
  - `tests/test_atomic_assignment.py`: 3 tests verifying single assignment, batch assignment, and a 20-thread concurrency hammer (0 double bookings).
  - `tests/test_outbox.py`: 3 tests verifying transactional outbox commitment, mock notification service deduplication, and worker batch dispatch.
- **Verification**:
  - `pytest tests/ -v` passed **17/17 tests (100%)** in 2.31s.

---

### [2026-11-13 01:09] — Phase 1: Storage, Contract & Dual FastAPI Instances Complete
- **Type**: `[FEATURE]` / `[BACKEND]` / `[TEST]`
- **Trigger**: Execution of Phase 1 milestone.
- **Files Created / Modified**:
  - `app/config.py`: Centralized environment configuration (instance IDs, ports 8000/8001, database path, Redis URL, Bengaluru spatial bounding box).
  - `app/database.py`: SQLite connection factory configured with WAL mode (`PRAGMA journal_mode=WAL;`), `busy_timeout=5000;`, auto-commit context manager, and schema initialization.
  - `app/redis_client.py`: Synchronous and asynchronous Redis client pools with safe connectivity check, auto-reconnect, and degraded-mode handling.
  - `app/main.py`: FastAPI application factory with CORS middleware, static file mounting at `/static`, and `/health` routing.
  - `app/main_a.py`: Entrypoint for Instance A (port 8000).
  - `app/main_b.py`: Entrypoint for Instance B (port 8001).
  - `app/routers/health.py`: Health check router (`/health` and `/metrics`) evaluating SQLite and Redis status, returning degraded flag on Redis disconnect.
  - `scripts/init_db.py`: Standalone script to initialize SQLite tables (`orders`, `outbox`, `processed_notifications`, `order_events`, `location_history`, `idempotency_keys`).
  - `scripts/run_instance_a.bat`: Launcher for Instance A on port 8000.
  - `scripts/run_instance_b.bat`: Launcher for Instance B on port 8001.
  - `scripts/start_all.bat`: One-click master startup script.
  - `tests/test_phase1_foundation.py`: Test suite validating WAL mode, tables, Redis connection, and health responses on both Instance A and Instance B.
- **Verification**:
  - `python scripts/init_db.py` executed successfully; all 6 tables created.
  - `pytest tests/test_phase1_foundation.py -v` passed 5/5 tests (100%).

---

### [2026-11-13 00:58] — Hackathon Phased Architecture & Judge-Driven Invariants
- **Type**: `[REFACTOR]` / `[HACKATHON-PHASING]`
- **Trigger**: Critical review calibration (splitting big-bang build into 4 executable verified milestones and fixing judge failure test gaps).
- **Files Modified**:
  - `BASE_PROMPT.md`: Completely reorganized into 4 phased milestones with explicit verification gates after each phase.
  - Added real **Mock Notification Service on Port 9000** (`app/mock_notification_service.py`) to survive genuine process shutdown and restart.
  - Added **Batch Assignment Lua Script** (`assign_batch.lua`) to pass the judge test where two batches compete for one rider.
  - Added **Rider-to-Order Mapping** in `ingest_location.lua` via `active_order_id`.
  - Added the **5 exact dashboard metrics** from the handbook (updates/sec, delivery latency p95, active viewers, DB writes/sec, pending notifications).
  - Explicitly defined the 4 Chaos modes for the fleet simulator (clean, noisy, duplicate, burst).

---

### [2026-11-13 00:43] — Project Planning, Contracts & Environment Setup
- **Type**: `[DOCS]` / `[CONFIG]` / `[ENVIRONMENT]`
- **Trigger**: Initial project setup and environment analysis prompt.
- **Files Created**:
  - `tools/redis/`: Redis 7.2.5 portable Windows binaries installed and verified.
  - `run_redis.bat`, `redis_cli.bat`: Root helper scripts for starting Redis on port 6379 and running CLI monitor.
  - `.planning/config.json`: GSD workflow configuration.
  - `.planning/PROJECT.md`: Vision, architecture constraints, and target metrics.
  - `.planning/REQUIREMENTS.md`: Detailed functional/resilience requirements and REQ IDs.
  - `.planning/ROADMAP.md`: 7 execution phases aligned with hackathon timeline.
  - `.planning/STATE.md`: Execution state tracker and readiness record.
  - `SPEC.md`: Master technical contract.
  - `requirements.txt`: Python dependencies.
  - `.gitignore`: Ignoring build artifacts, database files, and Redis logs/dumps.
  - `BASE_PROMPT.md`: Complete autonomous execution prompt for the platform.
  - `MANUAL_INTERACTION_LOG.md`: Under-the-hood backend & Redis reactivity trace.
  - `PS_PROGRESS.md`: Problem Statement tasks and deliverables tracker.

---

## Phase 4 Changes & Deliverables — Completed 2026-11-13

### 1. Resilient WebSocket Failover Client
- **`static/js/ws.js`**: Built resilient dual-instance client supporting automatic instant failover between port 8000 and port 8001 in `< 500 ms` without page reload. Automatically transmits `{ "action": "hello", "last_event_id": "<id>" }` on connect to catch up on missed stream events from Redis Streams.

### 2. Frontend Testbed Portals
- **`static/index.html` & `static/js/tracker.js`**: Customer live tracking portal. Features Leaflet map centered on Bengaluru, smooth `requestAnimationFrame` lerping marker animation, client monotonic packet drop safeguard, and live 5-stage order progression stepper.
- **`static/restaurant.html` & `static/js/board.js`**: Restaurant Kanban board. Features 5 columns, HTML5 drag-and-drop, HTTP 409 Conflict card shake & snap-back, assigned rider badge, and real-time push from WebSocket `board:orders` with zero HTTP polling.
- **`static/ops.html` & `static/js/ops.js`**: Operations Control Center. High-performance HTML5 `<canvas>` rendering 2,000 riders @ 60 FPS, 5 real-time metric gauges (Updates/sec, Latency p95, Active Viewers, DB Writes/sec, Pending Outbox), and interactive zoom, pan, and filter controls.
- **`static/chaos.html` & `static/js/chaos.js`**: Chaos Control Console. Dark-mode hacker console with 5 adversarial strike buttons to demonstrate failure scenarios live to hackathon judges.

### 3. Chaos API Router & Health Metrics
- **`app/routers/chaos.py`**: Added `/chaos/inject-gps`, `/chaos/burst-orders`, `/chaos/competing-batch`, `/chaos/check-notifications`, and `/chaos/kill-instance` endpoints.
- **`app/routers/health.py`**: Enhanced `/metrics` endpoint to return live operational metrics (active viewers, pending outbox, total orders, updates/sec, db writes).

### 4. Simulators & 1,000-Scenario Stress Benchmark
- **`simulator/fleet_sim.py`**: Virtual fleet simulator supporting up to 2,000 riders in Bengaluru with `clean`, `noisy` (backward/stale sequence packets), and `burst` modes.
- **`simulator/viewer_sim.py`**: Concurrent viewer simulator opening WebSockets to `/ws/orders/{id}` to measure message delivery latency.
- **`scripts/benchmark_1000_scenarios.py`**: Automated stress benchmark running 1,000 real scenarios with `time.perf_counter()` precision timing.
- **`BENCHMARK_SCORECARD.json`**: Verified audit scorecard proving 100% pass rate (1,000/1,000 passed, p95 assignment latency = 0.91 ms, 0 double bookings, 0 duplicate notifications, 0 backward marker jumps, DB writes = 33.3 writes/s).

### 5. Design Defence & Documentation Deliverables
- **`ARCHITECTURE.md`**: Complete distributed system architecture topology, data flow, and failover sequence.
- **`DECISION_RECORD.md`**: 1-Page Architecture Decision Record answering all 8 judge interview defence questions.
- **`scripts/start_all.bat`**: Master 1-click launcher starting all cluster processes.
- **`tests/test_chaos_and_benchmarks.py`**: Test suite covering chaos endpoints and frontend serving (28/28 total tests passing).
