"""
CrumbTail — One-Command Live Bangalore Demo Orchestrator.
Starts all microservices and simulators, seeds 50 Bangalore riders, and prints live URLs.
Works on Windows and POSIX.
"""
import sys
import os
import time
import subprocess
import signal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Ensure Python 3.10+
if sys.version_info < (3, 10):
    print("❌ Python 3.10+ required.")
    sys.exit(1)

processes = []

def cleanup(sig=None, frame=None):
    print("\n🛑 Shutting down CrumbTail live demo cluster...")
    for p, name in reversed(processes):
        try:
            print(f"  Stopping {name} (PID: {p.pid})...")
            p.terminate()
            p.kill()
        except Exception:
            pass
    print("✓ All processes stopped.")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def check_redis():
    """Verifies Redis is reachable or starts local windows binary."""
    from app.redis_client import check_redis
    if check_redis():
        print("✓ Redis is running on localhost:6379.")
        return

    print("⚡ Starting bundled Redis Server...")
    redis_exe = ROOT_DIR / "tools" / "redis" / "redis-server.exe"
    redis_conf = ROOT_DIR / "tools" / "redis" / "redis.conf"
    if redis_exe.exists():
        cmd = [str(redis_exe)]
        if redis_conf.exists():
            cmd.append(str(redis_conf))
        p = subprocess.Popen(cmd, cwd=str(ROOT_DIR))
        processes.append((p, "Redis Server"))
        time.sleep(1.5)
        if check_redis():
            print("✓ Bundled Redis Server started successfully.")
            return

    print("❌ Could not connect to Redis on localhost:6379. Please start Redis and rerun.")
    sys.exit(1)

def main():
    print("=" * 70)
    print("      CRUMB TRAIL — LIVE BANGALORE DEMO ORCHESTRATOR (50 RIDERS)     ")
    print("=" * 70)

    # 1. Check Redis
    check_redis()

    # 2. Reset and seed Bangalore data in Redis and SQLite
    print("\n📍 Seeding Bangalore 15 restaurants and 50 riders across city hubs...")
    from app.seed.bangalore import BANGALORE_RESTAURANTS, RIDER_HUBS
    from app.redis_client import get_sync_redis
    r = get_sync_redis()
    
    # Flush existing demo keys
    for key in r.scan_iter("rider:*:seq"):
        r.delete(key)
    for key in r.scan_iter("rider:*:latest"):
        r.delete(key)
    r.delete("riders:geo", "orders:pending")
    for key in r.scan_iter("order:demo_*"):
        r.delete(key)
        
    # Seed restaurants
    for rest in BANGALORE_RESTAURANTS:
        r.hset(f"restaurant:{rest['id']}", mapping={
            "id": rest["id"], "name": rest["name"], "lat": str(rest["lat"]),
            "lon": str(rest["lon"]), "locality": rest["locality"], "weight": str(rest["weight"])
        })
    r.set("demo:restaurants", str(BANGALORE_RESTAURANTS))
    
    # Seed 50 riders
    now_ts = str(int(time.time()))
    base_seq = int(time.time() * 1000)
    for i in range(1, 51):
        rid = f"rider_{i:04d}"
        hub_lat, hub_lon, locality = RIDER_HUBS[i % len(RIDER_HUBS)]
        r.geoadd("riders:geo", (hub_lon, hub_lat, rid))
        r.hset(f"rider:{rid}:latest", mapping={
            "status": "free", "state": "idle", "lat": str(hub_lat), "lon": str(hub_lon),
            "seq": str(base_seq + i), "active_order_id": "", "locality": locality, "updated_at": now_ts
        })
        r.set(f"rider:{rid}:seq", str(base_seq + i))
    print("✓ 50 riders registered in Redis geospatial index with monotonic sequences.")

    # 3. Start Notification Service (Port 9000)
    print("\n🚀 Starting Standalone Notification Service on port 9000...")
    p_notif = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.mock_notification_service:app", "--host", "0.0.0.0", "--port", "9000"],
        cwd=str(ROOT_DIR)
    )
    processes.append((p_notif, "Notification Service (:9000)"))

    # 4. Start Outbox Worker
    print("🚀 Starting Transactional Outbox Worker daemon...")
    p_outbox = subprocess.Popen([sys.executable, "app/outbox_worker.py"], cwd=str(ROOT_DIR))
    processes.append((p_outbox, "Outbox Worker"))

    # 5. Start Instance A (Port 8000)
    print("🚀 Starting FastAPI Instance A on port 8000...")
    p_a = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main_a:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(ROOT_DIR)
    )
    processes.append((p_a, "Instance A (:8000)"))

    # 6. Start Instance B (Port 8001)
    print("🚀 Starting FastAPI Instance B on port 8001...")
    p_b = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main_b:app", "--host", "0.0.0.0", "--port", "8001"],
        cwd=str(ROOT_DIR)
    )
    processes.append((p_b, "Instance B (:8001)"))

    time.sleep(2.0)

    # 7. Start Rider Simulator (50 riders, 5x speed)
    print("🛵 Starting Bangalore 50-Rider Simulator (A* routing, 5x speed)...")
    p_sim = subprocess.Popen(
        [sys.executable, "sim/riders.py", "--riders", "50", "--speed", "5", "--url", "http://localhost:8000"],
        cwd=str(ROOT_DIR)
    )
    processes.append((p_sim, "Rider Simulator"))

    # 8. Start Restaurant Simulator
    print("🍳 Starting Restaurant Simulator (Auto-advance & Dispatcher)...")
    p_rest = subprocess.Popen(
        [sys.executable, "sim/restaurant_sim.py", "--url", "http://localhost:8000"],
        cwd=str(ROOT_DIR)
    )
    processes.append((p_rest, "Restaurant Simulator"))

    print("\n" + "=" * 70)
    print("            CRUMB TRAIL LIVE DEMO PLATFORM IS RUNNING!            ")
    print("=" * 70)
    print("\n  👉 1. Demo Control (1-Click 120 Orders): http://localhost:8000/static/demo.html")
    print("  👉 2. Customer Live Tracking Page:      http://localhost:8000/static/index.html")
    print("  👉 3. Restaurant Order Kanban Board:    http://localhost:8000/static/restaurant.html")
    print("  👉 4. Operations Map (50 Riders Live):  http://localhost:8000/static/ops.html")
    print("  👉 5. Chaos Engineering Testbed:       http://localhost:8000/static/chaos.html")
    print("\n  (Press Ctrl+C to stop all cluster services)\n")

    # Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()

