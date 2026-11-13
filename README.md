# 🚀 Crumb Tail — Real-Time Delivery Tracking on Redis

**Yuktik 26 Hackathon Challenge**  
*High-Throughput Distributed Delivery Tracking Platform with Zero Polling & High Resilience*

Crumb Tail is a real-time food delivery tracking system designed for extreme scale and fault tolerance. It runs across two stateless FastAPI instances, Redis 7 (ephemeral coordinates, atomic Lua state locks, Pub/Sub, and Streams), and SQLite (ACID authoritative order state + Transactional Outbox).

---

## ⚡ Key Guarantees & Benchmarks

- **Zero Polling**: 100% real-time push via WebSockets across all portals.
- **Nearest-Rider Latency**: **$0.45\text{ ms}$ (p95)** ($< 50\text{ ms}$ target).
- **Double Assignments**: **Strictly 0** under heavy 20-order concurrent race bursts via atomic `assign_rider.lua`.
- **Monotonic GPS Ingestion**: Zero backward marker jumps via edge Lua filter (`seq <= stored_seq` drop).
- **Transactional Outbox**: Guaranteed at-least-once alert dispatch with **0 duplicate alerts** verified in persistent ledger.
- **Instant Client Failover**: Reconnects from Instance A (port 8000) to Instance B (port 8001) in **$< 500\text{ ms}$** with Redis Stream catch-up replay.
- **Database Write Downsampling**: 2,000 riders sampled at 1 pt/min $\rightarrow$ **$33.3\text{ writes/s}$** ($< 50\text{ writes/s}$ target).
- **1,000-Scenario Stress Pass Rate**: **100.0% (1,000 / 1,000 passed)**.

---

## 💻 Quick Start

### 1. Prerequisites
- **Python**: Compatible with Python 3.9, 3.10, 3.11, 3.12, 3.13, and 3.14.
- **Redis 7**:
  - *Windows*: Pre-packaged portable Redis 7 binaries are included in `tools/redis/`.
  - *Linux / macOS*: Install via package manager (`sudo apt install redis-server` or `brew install redis`).

### 2. Clone & Install
```bash
git clone https://github.com/harshithchennabathny-a11y/CrumbTail.git
cd CrumbTail

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Launch Cluster

#### On Windows:
Make sure Redis is running (`.\run_redis.bat`), then execute:
```cmd
scripts\start_all.bat
```

#### On Linux / macOS:
Make sure Redis is running (`redis-server`), then execute:
```bash
chmod +x scripts/start_all.sh
./scripts/start_all.sh
```

---

## 🌐 Interactive Portals

Once the cluster is running, open any portal in your browser:

| Portal | URL Link | Description |
| :--- | :--- | :--- |
| **📍 Customer Live Map** | [http://localhost:8000/static/index.html](http://localhost:8000/static/index.html) | Leaflet map with lerping rider marker, dynamic ETA, and instant WebSocket failover. |
| **📋 Restaurant Kanban** | [http://localhost:8000/static/restaurant.html](http://localhost:8000/static/restaurant.html) | Drag-and-drop order board with automatic snap-back on `HTTP 409 Conflict`. |
| **🌐 Operations 2,000 Radar** | [http://localhost:8000/static/ops.html](http://localhost:8000/static/ops.html) | HTML5 `<canvas>` rendering 2,000 moving dots at **60 FPS** with 5 live metric gauges. |
| **⚡ Chaos Control Console** | [http://localhost:8000/static/chaos.html](http://localhost:8000/static/chaos.html) | 6 adversarial trigger buttons for judges with a real-time dark execution console. |

---

## 🧪 Verification & Benchmarks

Run the complete automated test suite (40 tests across 10 modules):
```bash
pytest tests/ -v
```

Run the 1,000-scenario automated stress benchmark engine:
```bash
python scripts/benchmark_1000_scenarios.py
```

Run the 6 adversarial chaos strikes:
```bash
python scripts/run_chaos_scenarios.py
```

Run the live interactive order lifecycle demo:
```bash
python scripts/live_demo.py
```

---

## 📚 Technical Documentation
- **[SPEC.md](SPEC.md)**: API endpoints, Redis key schemas, and WebSocket contracts.
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: System topology, data flow, and failover sequence.
- **[DECISION_RECORD.md](DECISION_RECORD.md)**: 1-Page ADR answering 8 critical judge defence questions.
- **[BENCHMARK_SCORECARD.json](BENCHMARK_SCORECARD.json)**: Real statistical audit scorecard from 1,000 parallel test scenarios.
