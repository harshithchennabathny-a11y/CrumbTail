# Project Roadmap — Crumb Tail (Yuktik 26)

## Milestone 1: Hackathon Foundation & Resilience Delivery

### Phase 1: Architecture Foundation & Multi-Instance Skeleton
**Goal**: Establish dual stateless FastAPI instances, SQLite schema, Redis connectivity, and formal `SPEC.md` contract.
- Task 1.1: Author `SPEC.md` with explicit endpoints, Redis schemas, Lua scripts, and WebSocket payload formats.
- Task 1.2: Initialize database models (Orders, Outbox, OrderEvents, LocationHistory).
- Task 1.3: Set up dual FastAPI app instances (ports 8000 & 8001) sharing Redis & SQLite.
- Task 1.4: Implement health check, Redis ping, and degraded mode state indicator.
- *Verification*: Both instances boot, share DB/Redis, report healthy, and handle proxy requests.

### Phase 2: Order Lifecycle State Machine & Transactional Outbox
**Goal**: Enforce strict order progression, HTTP 409 conflict handling, idempotency, and transactional outbox.
- Task 2.1: Implement `POST /orders` and status transition endpoints (`placed` -> `accepted` -> `preparing` -> `picked_up` -> `delivered`, `cancelled`).
- Task 2.2: Enforce state machine constraints (HTTP 409 on invalid transition) and idempotency keys.
- Task 2.3: Transactional Outbox: atomic write of order status + outbox entry in single SQLite transaction.
- Task 2.4: Outbox worker process: polls pending outbox rows, dispatches with exponential backoff + jitter, marks sent.
- Task 2.5: Mock notification service with deduplication (`orderId:status`).
- *Verification*: Outbox tests prove zero lost and zero duplicate notifications even under notification server crash.

### Phase 3: Geospatial Index & Atomic Assignment Lua Scripts
**Goal**: Build nearest-rider discovery and zero-conflict atomic assignment.
- Task 3.1: Rider geo management (`riders:geo`, `GEOADD`, `GEOSEARCH` radius by distance).
- Task 3.2: Atomic single assignment Lua script: check free, mark busy, attach to order, remove from geo.
- Task 3.3: Batch assignment Lua script: check both orders and atomically assign both or neither.
- Task 3.4: Concurrency test suite hammering assignment from Instance A & B simultaneously.
- *Verification*: Target p95 $< 50$ ms, exactly 0 double assignments under extreme race conditions.

### Phase 4: Location Ingestion, Monotonic Dedup & DB Batching
**Goal**: High-throughput GPS ingest with backward-movement prevention and controlled DB writes.
- Task 4.1: `POST /locations` endpoint with sliding-window rate limit Lua script.
- Task 4.2: Ingestion Lua script: monotonic sequence check (`seq <= stored_seq`), drop duplicate/stale points, update live coordinates.
- Task 4.3: Redis Pub/Sub publishing to `track:{orderId}` channels for active orders.
- Task 4.4: Background DB batch sampler: accumulates 1 location per minute per active rider; bulk inserts to DB ($< 50$ writes/s).
- *Verification*: Monotonic test suite confirms out-of-order/stale packets are discarded; DB write frequency remains within bounds under 2,000 simulated riders.

### Phase 5: WebSockets, Stream Replay & Client Catch-Up [COMPLETED]
**Goal**: Zero-polling live updates with seamless reconnect catch-up and distributed presence.
- Task 5.1: WebSocket endpoints (`/ws/orders/{orderId}`, `/ws/ops`, `/ws/restaurant`) with targeted fan-out.
- Task 5.2: Dynamic Redis Pub/Sub listener: multiplexes frames to all local viewers; subscribes on first viewer, unsubscribes on last viewer disconnect.
- Task 5.3: Race-Free High-Watermark Redis Streams Replay: captures stream max ID, replays missed frames from client cursor up to watermark, then streams live frames without gaps.
- Task 5.4: Cluster-wide presence tracking in Redis (`presence:order:{order_id}`) across Instance A and B with rolling TTL.
- *Verification*: Zero polling; 3/3 automated catch-up tests passing in `tests/test_phase5_catchup.py`; instance termination results in < 500 ms client reconnect.

### Phase 6: Frontends & Real-Time Dashboards [COMPLETED]
**Goal**: Interactive visual applications for customers, restaurants, ops, and judges.
- Task 6.1: Customer Live Tracking Page (Leaflet / Canvas map, rider icon, status timeline, ETA, lerp interpolation).
- Task 6.2: Restaurant Order Board (Kanban drag-and-drop, optimistic update with automatic rollback on 409).
- Task 6.3: Operations Map & Live Metrics (2,000 riders @ 60 FPS on `<canvas>`, pan/zoom, 5 live metric gauges).
- Task 6.4: Chaos Panel with 6 judge-ready failure buttons and live dark-mode execution console.
- *Verification*: End-to-end user journeys working across both instances; verified by `tests/test_phase6_frontends.py` (5/5 passed; total suite 36/36 passed).

### Phase 7: Fleet Simulator, 1,000+ Scenario Stress Suite & Demo Rehearsal [COMPLETED]
**Goal**: Full load generation, massive dataset validation (1,000+ automated scenarios), and failover demo rehearsal.
- Task 7.1: Rider fleet simulator (`simulator/fleet_sim.py` supporting up to 2,000 riders, 1 Hz pings, clean/noisy/burst modes).
- Task 7.2: Viewer crowd simulator (`simulator/viewer_sim.py` supporting concurrent WebSocket viewers, hello handshake, frame tracking).
- Task 7.3: Chaos test scripts validating all 6 judge scenarios (`scripts/run_chaos_scenarios.py` verifying 6/6 strikes 100%).
- Task 7.4: **1,000-Scenario Stress & Benchmark Engine** (`scripts/benchmark_1000_scenarios.py`):
  - 1,000 concurrent scenarios (burst orders, high-density rider races, stale GPS packet drops, outbox worker dispatches).
  - Verified statistical scorecard in `BENCHMARK_SCORECARD.json` (100.0% passed, p95 = 0.45 ms, 0 double bookings, 0 duplicate alerts, 0 backward marker movements).
- Task 7.5: One-page Decision Record (`DECISION_RECORD.md`) & Architecture Topology (`ARCHITECTURE.md`).
- *Verification*: Complete dry run verified via `tests/test_phase7_simulators_and_chaos.py` (4/4 passed; full project test suite 40/40 passed).

