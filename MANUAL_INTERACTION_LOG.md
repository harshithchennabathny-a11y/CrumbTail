# Manual Interaction & Backend Reactivity Log — Crumb Trail

This document details **exactly what happens under the hood** across the entire backend (FastAPI, Redis engine, SQLite transactions, and WebSockets) whenever you interact with the UI on your screen.

---

## 1. Interaction Trace Map: Screen Action ➔ Backend Reaction

```
[ User Action on Screen ]
         │
         ▼
[ 1. HTTP / WebSocket Frame ]  ──► FastAPI Router (Instance A: 8000 or Instance B: 8001)
                                      │
         ┌────────────────────────────┴───────────────────────────┐
         ▼                                                        ▼
[ 2. Redis Reaction ]                                    [ 3. SQLite DB Reaction ]
• GEOSEARCH riders:geo                                   • BEGIN TRANSACTION
• Atomic Lua Script (check & lock)                       • UPDATE orders SET status=...
• HSET rider:{id}:latest                                 • INSERT INTO outbox (orderId:status)
• PUBLISH track:{orderId}                                • COMMIT TRANSACTION
• XADD stream:order:{orderId}                                     │
         │                                                        ▼
         │                                              [ 4. Outbox Worker ]
         ▼                                              • Polls pending outbox rows
[ 5. WebSocket Push ]                                   • Dispatches with backoff + jitter
• track:{orderId} frame received                        • Enforces idempotency key
• Browser lerps marker smoothly                                   │
         │                                                        ▼
         └───────────────────► [ 6. UI Update ] ◄─────────────────┘
                               • Kanban card moves
                               • Map marker glides
                               • Metric gauges update
```

---

## 2. Step-by-Step Under-The-Hood Traces for Every Screen Action

### Action 1: You Click "Place Order" (Customer Page: `index.html`)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | Browser sends `POST /orders` with `{ "customer_id": "cust_101", "restaurant_id": "rest_1", "items": [...] }`. |
| **FastAPI Backend** | `routers/orders.py` validates request body via Pydantic; generates a new `order_id` (e.g. `ord_8891`). |
| **SQLite Reaction** | Executes `INSERT INTO orders (id, customer_id, restaurant_id, status) VALUES ('ord_8891', ..., 'placed')`. |
| **Redis Reaction** | • Executes `HSET order:ord_8891 status placed created_at <timestamp>` (hot order cache).<br>• Executes `XADD stream:order:ord_8891 * type status status placed` (append-only stream for reconnect replay).<br>• Executes `PUBLISH board:orders {"event": "order_created", "order_id": "ord_8891"}`. |
| **WebSocket Reaction**| The restaurant order board (subscribed to `board:orders`) instantly receives the event without polling. |
| **Screen Update** | • Customer Page: Shows status stepper at **Placed**, creates WebSocket connection to `/ws/orders/ord_8891`.<br>• Restaurant Board: A new order card pops up in the **"Placed"** column. |

---

### Action 2: You Drag Order from "Placed" to "Accepted" (Restaurant Board: `restaurant.html`)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | You drop the card into the "Accepted" column. Browser sends `POST /orders/ord_8891/status` with `{ "status": "accepted", "idempotency_key": "uuid-1" }`. |
| **FastAPI Backend** | • Checks state machine: `placed` $\rightarrow$ `accepted` is a **legal transition**.<br>• Opens a database transaction. |
| **SQLite Reaction** | **Single Atomic Transaction**:<br>`UPDATE orders SET status = 'accepted' WHERE id = 'ord_8891';`<br>`INSERT INTO outbox (order_id, status, event_key, state) VALUES ('ord_8891', 'accepted', 'ord_8891:accepted', 'pending');`<br>`INSERT INTO order_events (order_id, from_status, to_status) VALUES ('ord_8891', 'placed', 'accepted');`<br>`COMMIT;` |
| **Redis Reaction** | **1. Rider Assignment via Atomic Lua Script**:<br>• Runs `GEOSEARCH riders:geo FROMLONLAT <rest_lon> <rest_lat> BYRADIUS 5 km ASC` to find closest free riders.<br>• Executes `assign_rider.lua`: Checks if `rider:r_42:latest` status == `free`. If free, atomically sets status to `busy`, sets `active_order_id = ord_8891`, and executes `ZREM riders:geo r_42`. Zero chance of double-booking.<br>• Executes `HSET order:ord_8891 status accepted rider_id r_42`.<br>• Executes `XADD stream:order:ord_8891 * type status status accepted rider_id r_42`.<br>• Executes `PUBLISH track:ord_8891 {"type": "assigned", "rider_id": "r_42"}`. |
| **Outbox Worker** | Background worker detects pending row in SQLite outbox; sends notification to mock notification service with key `ord_8891:accepted`; marks row `sent`. |
| **Screen Update** | • Restaurant card shows: **"Assigned to Rider r_42"**.<br>• Customer tracking page receives WS message: updates stepper to **"Accepted"**, renders rider marker on map. |

---

### Action 3: You Drag Order Illegally from "Placed" to "Delivered" (Restaurant Board)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | You drop a card from "Placed" straight into "Delivered". Browser optimistically moves card and sends `POST /orders/ord_8891/status` with `status: "delivered"`. |
| **FastAPI Backend** | State machine validator evaluates transition: `placed` $\rightarrow$ `delivered` is **ILLEGAL** (skips `accepted`, `preparing`, `picked_up`). Immediately raises `HTTP 409 Conflict`. |
| **SQLite & Redis** | **Zero changes**. Database transaction is never opened; Redis keys remain completely untouched. |
| **Screen Update** | Browser receives `409 Conflict`. The UI displays a red toast: *"409 Conflict: Invalid State Transition"*, and the card automatically animates/snaps back to the **"Placed"** column. |

---

### Action 4: Rider Simulator Sends Live GPS Coordinates (Background / Ops Page)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Simulator** | Rider `r_42` moves along route, sending `POST /locations` every second with `{ "rider_id": "r_42", "lat": 12.9716, "lon": 77.5946, "seq": 105, "ts": 1731456000 }`. |
| **FastAPI Backend** | Rate limiter Lua script checks request rate under sliding window; then executes `ingest_location.lua`. |
| **Redis Reaction** | **Monotonic Ingestion Lua Script**:<br>• `GET rider:r_42:seq` $\rightarrow$ retrieves previous seq `104`.<br>• Checks `105 > 104`: Valid packet!<br>• Executes `SET rider:r_42:seq 105`.<br>• Executes `HSET rider:r_42:latest lat 12.9716 lon 77.5946 seq 105`.<br>• Checks if rider has active order (`ord_8891`). If yes, executes `PUBLISH track:ord_8891 {"type": "location", "lat": 12.9716, "lon": 77.5946, "seq": 105}`. |
| **SQLite Reaction** | **No write happens immediately!** (Avoids DB overload). Only once per minute does the background sampler batch-insert 1 point per active rider to `location_history` ($< 50$ DB writes/s). |
| **WebSocket Reaction**| FastAPI instance subscribed to Redis channel `track:ord_8891` receives the frame and pushes it directly down the WebSocket to the customer's browser. |
| **Screen Update** | Customer map: JavaScript receives `seq: 105`, runs `requestAnimationFrame` linear interpolation (lerp), and smoothly glides the bike marker to the new coordinate at 60 FPS. |

---

### Action 5: You Click "Inject Stale GPS Data" (Chaos Panel: `chaos.html`)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | You click the chaos button. Chaos client sends `POST /locations` with an intentionally stale sequence: `seq: 95` (while Redis has `seq: 105`). |
| **Redis Reaction** | **`ingest_location.lua` executes**:<br>• Compares incoming `seq: 95` against stored `105`.<br>• Condition `95 <= 105` is TRUE $\rightarrow$ packet is classified as **stale / duplicate**.<br>• Script returns `0` (rejected). It does **NOT** update the coordinate and does **NOT** publish to Pub/Sub. |
| **Screen Update** | • Chaos Panel log: Displays *"Dropped duplicate/stale packet (seq 95 <= 105)"*.<br>• Customer Map: Marker stays completely still. **Proves the marker never moves backwards.** |

---

### Action 6: You Click "Disconnect WS", Wait, then Click "Reconnect WS" (Customer Page)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | • You click "Disconnect WS": Browser closes WebSocket connection. While disconnected, restaurant changes status to `preparing`.<br>• You click "Reconnect WS": Browser opens new WebSocket to `/ws/orders/ord_8891`. |
| **Handshake Protocol**| On connect, browser automatically transmits the handshake frame:<br>`{ "action": "hello", "last_event_id": "1731456000-0" }` |
| **Redis Reaction** | • FastAPI reads `last_event_id` and queries Redis Stream: `XRANGE stream:order:ord_8891 (1731456000-0 +`.<br>• Redis returns the missed `status: preparing` event from memory.<br>• Server pushes the missed event to the client.<br>• Server executes `SUBSCRIBE track:ord_8891` to resume live streaming. |
| **Screen Update** | Customer page catches up instantly: status stepper updates to **"Preparing"** without requiring a page reload. |

---

### Action 7: You Click "Kill Instance A" (Chaos Panel: `chaos.html`)

| Layer | What Happens Under the Hood |
| :--- | :--- |
| **Frontend** | You trigger the kill button. Chaos endpoint sends termination signal to Instance A (port 8000). |
| **FastAPI Backend** | Instance A OS process terminates (`os._exit(0)`). The TCP connection to all connected WebSockets drops. |
| **Client Reaction** | Browser `ws.js` detects `onclose` event.<br>• Reconnect loop triggers immediately with fallback URL: `ws://localhost:8001/ws/orders/ord_8891` (Instance B).<br>• Reconnect completes in $\approx 200 - 500$ ms. |
| **Instance B Reaction**| Instance B receives connection, reads the `hello` handshake with last event ID from the client, replays any missed stream events, and attaches to Redis Pub/Sub. |
| **Screen Update** | Green banner flashes on customer screen: *"Reconnected to Instance B (Port 8001)"*. Live tracking continues seamlessly without losing state. |

---

## 3. Real-Time Interaction Verification Log

| Timestamp | User Action | Endpoint / WS | Redis Command(s) Fired | SQLite Query Fired | Observed UI Behavior | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: |
| *Pending* | Click "Place Order" | `POST /orders` | `HSET`, `XADD`, `PUBLISH` | `INSERT INTO orders` | Order appears in Placed column | `READY` |
| *Pending* | Drag to Accepted | `POST /orders/{id}/status` | `GEOSEARCH`, `assign_rider.lua` | Atomic `UPDATE` + `outbox` | Card shows assigned rider ID | `READY` |
| *Pending* | Drag Placed -> Delivered | `POST /orders/{id}/status` | *(None - rejected)* | *(None - rejected)* | 409 toast + card snaps back | `READY` |
| *Pending* | Stale GPS injection | `POST /locations` | `ingest_location.lua` (returns 0) | *(None - dropped)* | Drop logged; marker steady | `READY` |
| *Pending* | Kill Instance A | `POST /chaos/kill_a` | *(None - process killed)* | *(None)* | Reconnects to 8001 in < 500ms | `READY` |
