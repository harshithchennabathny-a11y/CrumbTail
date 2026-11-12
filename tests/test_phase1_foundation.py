import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from app.database import init_db, get_connection, check_db
from app.redis_client import check_redis
from app.main_a import app as app_a
from app.main_b import app as app_b

@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Ensure database tables are created before running tests."""
    init_db()

def test_sqlite_wal_mode_and_tables():
    """Verifies SQLite is operating in WAL mode with all required tables."""
    assert check_db() is True
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Verify WAL mode
    cursor.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    assert mode.lower() == "wal", f"Expected WAL mode, got {mode}"
    
    # Verify tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cursor.fetchall()}
    required_tables = {"orders", "outbox", "order_events", "location_history", "idempotency_keys", "processed_notifications"}
    assert required_tables.issubset(tables), f"Missing tables: {required_tables - tables}"
    
    cursor.close()
    conn.close()

def test_redis_connection_healthy():
    """Verifies that Redis 7 is reachable on localhost:6379."""
    assert check_redis() is True, "Redis connection failed. Ensure Redis 7 is running on port 6379."

def test_instance_a_health():
    """Verifies FastAPI Instance A health endpoint."""
    client_a = TestClient(app_a)
    response = client_a.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["instance"] == "A"
    assert data["database"] is True
    assert data["redis"] is True

def test_instance_b_health():
    """Verifies FastAPI Instance B health endpoint."""
    client_b = TestClient(app_b)
    response = client_b.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["instance"] == "B"
    assert data["database"] is True
    assert data["redis"] is True

def test_static_files_served():
    """Verifies that static assets are mounted and served."""
    client_a = TestClient(app_a)
    response = client_a.get("/static/index.html")
    assert response.status_code == 200
    assert "Crumb Trail Platform" in response.text
