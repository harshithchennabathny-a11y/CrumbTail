# Crumb Tail (Yuktik 26) — Real-Time Delivery Tracking on Redis

## 1. Project Vision
Crumb Tail is a real-time food delivery tracking platform built to handle the intense dinner rush load: 2,000+ active simulated riders updating locations every second, thousands of concurrent viewers, and burst order placements.

The platform eliminates the 5 classic distributed tracking pitfalls:
1. **Database Overload**: Keep 1 Hz live locations in Redis; downsample/batch-write to SQLite once a minute per active rider (< 50 DB writes/s).
2. **Polling Storms**: WebSockets for targeted push (`track:{orderId}`), ensuring zero HTTP polling.
3. **Double Assignment**: Atomic Redis Lua scripts evaluate rider availability, distance, and lock riders in one uninterruptible step.
4. **Duplicate & Stale GPS Data**: Monotonic sequence numbers (`seq`) reject old/duplicate coordinates in an ingest Lua script, guaranteeing markers never jump backward.
5. **Fragile Connections**: Stateless dual FastAPI instances with Redis Streams for event replay, enabling sub-second reconnects without page reloads.

---

## 2. Core Tech Stack
- **Backend**: Python 3.14 + FastAPI + Uvicorn (Stateless Dual Instances A & B)
- **Real-Time Data Tier**: Redis 7+ (GEO search, Pub/Sub, Streams, Lua scripts, sliding-window rate limiters)
- **Relational Storage (Source of Truth)**: SQLite (ACID transactions, Order state, Transactional Outbox, Sampled history)
- **Frontend / Dashboards**: Vanilla HTML5/JS/Canvas/CSS (or lightweight modern frontend):
  - Customer Live Tracking Page (smooth interpolation, status timeline)
  - Restaurant Order Board (drag-and-drop order states with HTTP 409 rollback)
  - Operations Live Map & Real-time Metrics Dashboard
  - Chaos Injection Control Panel
- **Testing & Simulation**:
  - Fake Rider Fleet Simulator (2,000 riders, GPS drift, monotonic seq)
  - Fake Viewer Crowd Simulator (WebSocket subscribers)
  - Automated Chaos & Resilience Test Suite (pytest, httpx, websockets)

---

## 3. Strict Architectural Rules
1. **SPEC.md is the Contract**: Any changes to endpoints, Redis key schemas, or payloads must update `SPEC.md` first.
2. **Stateless App Instances**: Instances A & B must never communicate directly. All state and synchronization reside in Redis and the SQLite DB.
3. **Atomic Lua Locking**: No Python-level locks or external locking libraries. Atomic multi-key checks must be executed directly via Redis Lua scripts.
4. **Transactional Outbox for Notifications**: Never trigger notifications directly in an API handler. Insert outbox records inside the order update DB transaction; dispatch via a worker with backoff and jitter.
5. **Monotonic Sequence Enforcement**: GPS coordinates with `seq <= stored_seq` are rejected by Redis and discarded by frontend renderers.

---

## 4. Evaluation Targets & Metrics
- **Map Delay**: $< 2$ seconds end-to-end
- **Polling Requests**: Exactly 0
- **Database Location Writes**: $< 50$ writes/sec under 2,000 riders
- **Nearest-Rider Assignment Latency**: p95 $< 50$ ms
- **Double Assignments**: Exactly 0
- **Duplicate Notifications**: Exactly 0
- **Rider Marker Movement**: Monotonic (never backward)
- **Score Weighting**: Foundation (35) · Resilience (30) · Production Readiness (25) · Design Defence (10)

