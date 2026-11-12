import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pytest
from fastapi.testclient import TestClient
from app.main_a import app
from app.redis_client import get_sync_redis
from app.location_sampler import flush_location_batch
from app.database import init_db, get_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean():
    init_db()
    r = get_sync_redis()
    r.delete("rider:r_mono:seq", "rider:r_mono:latest", "riders:geo")
    yield
    r.delete("rider:r_mono:seq", "rider:r_mono:latest", "riders:geo")

def test_monotonic_sequence_enforcement():
    """
    CRITICAL HACKATHON TEST:
    Verifies that packets with seq <= stored_seq are dropped by Redis Lua script.
    Guarantees the marker can never move backwards.
    """
    # 1. First valid packet (seq = 100)
    res1 = client.post("/locations", json={
        "rider_id": "r_mono",
        "lat": 12.9716,
        "lon": 77.5946,
        "seq": 100
    })
    assert res1.status_code == 200
    assert res1.json()["accepted"] is True
    
    # 2. Next valid packet (seq = 101)
    res2 = client.post("/locations", json={
        "rider_id": "r_mono",
        "lat": 12.9718,
        "lon": 77.5948,
        "seq": 101
    })
    assert res2.status_code == 200
    assert res2.json()["accepted"] is True
    
    # 3. Duplicate packet (seq = 101) -> DROPPED
    res_dup = client.post("/locations", json={
        "rider_id": "r_mono",
        "lat": 12.9718,
        "lon": 77.5948,
        "seq": 101
    })
    assert res_dup.status_code == 200
    assert res_dup.json()["accepted"] is False
    assert res_dup.json()["reason"] == "stale_or_duplicate_seq"
    
    # 4. Out-of-order stale packet (seq = 95) -> DROPPED
    res_stale = client.post("/locations", json={
        "rider_id": "r_mono",
        "lat": 12.9710,
        "lon": 77.5940,
        "seq": 95
    })
    assert res_stale.status_code == 200
    assert res_stale.json()["accepted"] is False
    assert res_stale.json()["reason"] == "stale_or_duplicate_seq"

def test_sliding_window_rate_limiting():
    """Flooding 30 pings in a sub-second burst triggers HTTP 429 Too Many Requests."""
    device_id = "device_flood_test_1"
    
    # First 25 requests should pass
    passed = 0
    blocked = 0
    for i in range(35):
        res = client.post("/locations", json={
            "rider_id": f"rider_flood_{i}",
            "lat": 12.9716,
            "lon": 77.5946,
            "seq": i + 1,
            "device_id": device_id
        })
        if res.status_code == 200:
            passed += 1
        elif res.status_code == 429:
            blocked += 1
            
    assert passed <= 25
    assert blocked >= 1, "Rate limiter failed to block flooding device!"

def test_downsampled_database_batch_persistence():
    """Verifies that location sampling buffers points and bulk-inserts to SQLite location_history."""
    # Ingest a point
    client.post("/locations", json={
        "rider_id": "rider_persisted",
        "lat": 12.9720,
        "lon": 77.5950,
        "seq": 500
    })
    
    # Force batch flush
    flushed = flush_location_batch()
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT rider_id, latitude, longitude, seq FROM location_history WHERE rider_id = 'rider_persisted';")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "rider_persisted"
        assert row[3] == 500
        cursor.close()

