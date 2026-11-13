#!/usr/bin/env bash
# Crumb Trail - Unix/Linux/macOS Cluster Startup
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "==================================================="
echo "  Crumb Trail - Multi-Instance Startup (Unix)"
echo "==================================================="

PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# 1. Initialize SQLite Database (WAL Mode)
echo "1. Initializing SQLite Database (WAL Mode)..."
$PYTHON_CMD scripts/init_db.py

# 2. Start Notification Service on port 9000
echo "2. Starting Notification Service on port 9000..."
$PYTHON_CMD -m uvicorn app.mock_notification_service:app --host 0.0.0.0 --port 9000 &
PID_NOTIF=$!

# 3. Start Transactional Outbox Worker
echo "3. Starting Transactional Outbox Worker..."
$PYTHON_CMD app/outbox_worker.py &
PID_OUTBOX=$!

# 4. Start Instance A on port 8000
echo "4. Starting FastAPI Instance A on port 8000..."
$PYTHON_CMD -m uvicorn app.main_a:app --host 0.0.0.0 --port 8000 &
PID_A=$!

# 5. Start Instance B on port 8001
echo "5. Starting FastAPI Instance B on port 8001..."
$PYTHON_CMD -m uvicorn app.main_b:app --host 0.0.0.0 --port 8001 &
PID_B=$!

echo ""
echo "==================================================="
echo "              CRUMB TAIL CLUSTER ACTIVE            "
echo "==================================================="
echo "  Portals:"
echo "  - 📍 Customer Live Map:       http://localhost:8000/static/index.html"
echo "  - 📋 Restaurant Kanban:       http://localhost:8000/static/restaurant.html"
echo "  - 🌐 Operations 2,000 Radar:  http://localhost:8000/static/ops.html"
echo "  - ⚡ Chaos Control Console:   http://localhost:8000/static/chaos.html"
echo ""
echo "  API Backends:"
echo "  - Instance A (8000):          http://localhost:8000/docs"
echo "  - Instance B (8001):          http://localhost:8001/docs"
echo "  - Notifications (9000):       http://localhost:9000/notifications"
echo "==================================================="
echo "Press Ctrl+C to terminate all cluster processes."

trap "kill $PID_NOTIF $PID_OUTBOX $PID_A $PID_B 2>/dev/null || true" EXIT INT TERM
wait

