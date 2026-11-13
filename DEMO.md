# Crumb Trail — 2-Minute Live Demo Script for Judges

## Quick Start (One Command)
Run from the repository root:
```bash
python run_demo.py
```
This automatically verifies Redis, seeds 50 Bangalore delivery partners across 15 restaurants, starts dual FastAPI instances (8000 & 8001), notification worker, and autonomous simulators.

---

## 2-Minute Judge Walkthrough

### 1. The Demo Dashboard (`http://localhost:8000/static/demo.html`)
- **Show the Live Metrics**: Point out the live telemetry metrics:
  - **Location Updates / sec**: Live 1 Hz GPS ingest rate.
  - **GEOSEARCH p95**: Sub-millisecond (< 50 ms target) geospatial lookup.
  - **A\* Route p95**: Instant pure Python A\* road routing.
  - **DB writes / sec**: strictly rate-limited and sampled (< 50/s) so SQLite is never choked.
- **Click "📦 Place 120 Orders Now"**:
  - 120 orders are placed instantaneously across Bangalore hotspots (Koramangala, Indiranagar, HSR, MG Road).
  - 50 orders are immediately matched to the 50 free riders.
  - 70 surplus orders smoothly enter the Redis **Pending Queue** (`orders:pending`).
- **Show the Invariant Auditor**:
  - The green status panel displays `0 Violations`.
  - Verifies zero double-bookings, valid same-restaurant batches (≤ 500m), and monotonic sequence integrity.

---

### 2. Live Customer Tracking & Privacy Proof (`http://localhost:8000/static/index.html`)
- **Live Order Picker**: Select any active order from the dropdown.
- **Smooth Road Navigation**: The delivery partner's motorcycle marker glides along the actual A\* road polyline using requestAnimationFrame linear interpolation (lerp).
- **Network Privacy Proof Guarantee**:
  - Show the **Privacy Proof panel**: Distinct Rider IDs received on this socket = **1**.
  - Proves strict channel isolation: customers only receive telemetry for their assigned rider via `track:{orderId}`.
- **Monotonic Packet Safeguard**:
  - Click `⚡ Inject Stale GPS`: Watch the client-side monotonic guard immediately reject the duplicate/stale packet without the marker jumping backwards.

---

### 3. Kitchen Operations Kanban (`http://localhost:8000/static/restaurant.html`)
- Displays live WebSocket sync without HTTP polling.
- Demonstrates state machine transitions: `Placed` → `Accepted` → `Preparing` → `Picked Up` → `Delivered`.
- Click `⚠️ 409 Conflict Test`: Demonstrates HTTP 409 Conflict rollback when attempting an illegal backwards transition.

---

### 4. Operations Map Radar (`http://localhost:8000/static/ops.html`)
- Shows all 50 delivery partners live across Bangalore.
- Color-coded state indicators:
  - 🟤 Idle (small drift random walk)
  - 🔵 En route to restaurant pickup (following A\* polyline)
  - 🟡 Waiting at kitchen hub
  - 🟢 En route to customer drop-off
- Filter by state or toggle the 15 restaurant pins.

---

### 5. High Availability & Failover (`http://localhost:8000/static/chaos.html`)
- Click **"☠️ Kill Instance A"** (or kill port 8000 process).
- Observe the WebSocket connection automatically fail over to **Instance B (port 8001)** in `< 500 ms` with Redis Stream high-watermark replay ensuring zero lost events.

