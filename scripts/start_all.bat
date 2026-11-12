@echo off
echo ===================================================
echo   Crumb Trail - Multi-Instance Startup (Yuktik 26)
echo ===================================================

cd /d "%~dp0.."

echo 1. Initializing SQLite Database (WAL Mode)...
python scripts\init_db.py

echo 2. Starting Notification Service on port 9000...
start "Crumb Trail - Notifications (9000)" cmd /k "python -m uvicorn app.mock_notification_service:app --host 0.0.0.0 --port 9000"

echo 3. Starting Transactional Outbox Worker Daemon...
start "Crumb Trail - Outbox Worker" cmd /k "python app\outbox_worker.py"

echo 4. Starting FastAPI Instance A on port 8000...
start "Crumb Trail - Instance A (8000)" cmd /k "python -m uvicorn app.main_a:app --host 0.0.0.0 --port 8000"

echo 5. Starting FastAPI Instance B on port 8001...
start "Crumb Trail - Instance B (8001)" cmd /k "python -m uvicorn app.main_b:app --host 0.0.0.0 --port 8001"

echo.
echo ===================================================
echo               CRUMB TAIL CLUSTER ACTIVE
echo ===================================================
echo   Portals:
echo   - 📍 Customer Live Map:       http://localhost:8000/static/index.html
echo   - 📋 Restaurant Kanban:       http://localhost:8000/static/restaurant.html
echo   - 🌐 Operations 2,000 Radar:  http://localhost:8000/static/ops.html
echo   - ⚡ Chaos Control Console:   http://localhost:8000/static/chaos.html
echo.
echo   API Backends:
echo   - Instance A (8000):          http://localhost:8000/docs
echo   - Instance B (8001):          http://localhost:8001/docs
echo   - Notifications (9000):       http://localhost:9000/ledger
echo ===================================================
echo.
pause
