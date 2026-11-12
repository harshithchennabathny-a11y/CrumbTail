# Crumb Tail — Architecture Decision Record (ADR)

**Document**: 1-Page Design Defence & Architectural Decisions  
**Challenge**: Yuktik 26 — Real-Time Delivery Tracking on Redis  
**Author**: Engineering Team  

---

## 1. Context & Problem Statement
A real-time delivery platform demands concurrent nearest-rider dispatch, 1 Hz real-time GPS telemetry from 2,000 riders, seamless client reconnects during server failures, and guaranteed zero duplicate notifications. Traditional monolithic relational architectures suffer from disk saturation, race conditions under burst ordering, and dual-write data corruption.

---

## 2. Decision Log & Rationale

### Decision 1: Redis as Ephemeral Telemetry Tier vs SQLite as Authoritative State
- **Choice**: Dual-tier storage split.
- **Why**: SQLite in WAL mode provides ACID transaction guarantees and persistent durability for financial/order records and the Transactional Outbox. Redis 7 provides in-memory sub-millisecond latencies ($p95 < 1\text{ ms}$) for ephemeral geospatial coordinates (`GEOSEARCH`), Pub/Sub fan-out, and stream event replay (`XADD`/`XRANGE`).
- **Alternative Rejected**: Storing 1 Hz GPS writes directly into SQLite exhausts disk I/O at 2,000 riders ($2,000\text{ writes/sec}$ vs SQLite target $< 50\text{ writes/sec}$).

### Decision 2: Atomic Lua Scripts vs Distributed Locks (Redlock)
- **Choice**: Single-shot atomic Lua scripts (`assign_rider.lua`, `assign_batch.lua`, `ingest_location.lua`).
- **Why**: Redis is single-threaded per event loop. A Lua script executes to completion without interleaving commands from other instances. This guarantees that `GEOSEARCH` + availability check + status mutation happen as a single atomic primitive with **zero lock acquisition overhead** and **zero double bookings**.
- **Alternative Rejected**: Redlock requires distributed network leases, clock synchronization, and complex TTL recovery, introducing 50–100ms latency under high contention.

### Decision 3: Zero HTTP Polling via Dual-Instance WebSockets
- **Choice**: WebSocket push with client-side failover protocol (`static/js/ws.js`).
- **Why**: Periodic HTTP polling floods backend servers and fails the $< 2\text{s}$ latency SLA. Dual-instance WebSockets allow instant $< 500\text{ms}$ failover: when Instance A drops, the client automatically switches to Instance B and catches up on missed events via Redis Streams.

### Decision 4: Monotonic Sequence Number Ingestion at Edge
- **Choice**: Lua-enforced `incoming_seq > stored_seq`.
- **Why**: Cell networks deliver out-of-order packets due to multi-path routing. Rejecting packets at the Redis ingress boundary prevents downstream database pollution and prevents map markers from moving backward.

---

## 3. Judge Interview Defence: Quick-Reference Answers

1. **Why not use Redis for orders too?**  
   *Answer*: Redis is an in-memory cache and ephemeral data structure store. Even with AOF fsync, unexpected hardware crashes or OOM kills can lose un-synced data. Orders, payments, and audit ledgers must reside in durable ACID storage (SQLite WAL). Redis holds only ephemeral coordinates and locks.

2. **How is "Zero Double Bookings" proved under concurrency?**  
   *Answer*: We ran a 400-scenario concurrency race hammer in `scripts/benchmark_1000_scenarios.py` where 20 concurrent requests competed for 1 rider simultaneously. Redis executes `assign_rider.lua` atomically. Exactly 1 request acquired the rider; 19 received no available rider. Measured double bookings: strictly 0.

3. **How does the client survive an instance crash in < 500ms?**  
   *Answer*: The client (`ws.js`) knows both instances (`:8000` and `:8001`). When the socket disconnects, it reconnects to the alternate port within 50ms and sends `{ "action": "hello", "last_event_id": "<id>" }`. Instance B reads `stream:order:{id}` using `XRANGE` from that cursor and pushes missed frames before resuming live Pub/Sub. No page refresh is required.

4. **How do you prevent duplicate notifications if the worker crashes?**  
   *Answer*: At-least-once outbox dispatch paired with an idempotent consumer ledger. When an order transitions, an outbox row is committed in the same SQLite transaction with key `orderId:status`. The notification service records processed keys in a unique SQLite index; duplicate dispatches return `already_processed` (HTTP 200) with zero duplicate alerts.

5. **How do 2,000 riders not overwhelm SQLite with 2,000 writes/sec?**  
   *Answer*: Redis absorbs all 1 Hz pings in memory. An in-memory downsampler persists only 1 point every 60 seconds per active rider to SQLite `location_history`, executing in bulk batches of 50. This caps database write throughput at 33.3 writes/second, safely below the 50 writes/second ceiling.

6. **What happens if Redis dies completely?**  
   *Answer*: `/health` returns `status: degraded` (HTTP 200). Order creation and state transitions continue safely in SQLite. The UI displays an amber degraded status banner. When Redis restarts, the application reconnects automatically.

