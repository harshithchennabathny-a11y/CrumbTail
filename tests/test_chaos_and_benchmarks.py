import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from app.main_a import app as app_a
from app.database import init_db
from app.redis_client import get_sync_redis

client = TestClient(app_a)

@pytest.fixture(autouse=True)
def setup_cluster():
    init_db()
    r = get_sync_redis()
    r.flushdb()

def test_chaos_inject_gps_packet_drop():
    """Verifies that injecting a backward sequence packet returns status='rejected'."""
    # Register test rider
    client.post("/riders/rider_chaos_test/register", json={"lat": 12.9716, "lon": 77.5946})
    
    # Store initial seq=10
    client.post("/locations", json={"rider_id": "rider_chaos_test", "lat": 12.9716, "lon": 77.5946, "seq": 10})

    # Inject backward seq=5
    res = client.post("/chaos/inject-gps", json={
        "rider_id": "rider_chaos_test",
        "latitude": 12.9720,
        "longitude": 77.5950,
        "seq": 5
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert "seq 5 <= stored_seq" in data["reason"]

def test_chaos_burst_orders_zero_double_bookings():
    """Verifies that a 20-order burst competing for 1 rider results in 0 double bookings."""
    # Register 1 rider
    client.post("/riders/rider_lone_wolf/register", json={"lat": 12.9716, "lon": 77.5946})

    # Burst 20 orders
    res = client.post("/chaos/burst-orders", json={
        "num_orders": 20,
        "latitude": 12.9716,
        "longitude": 77.5946
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_requests"] == 20
    assert data["successful_assignments"] == 1
    assert data["unassigned_orders"] == 19
    assert data["double_bookings"] == 0
    assert data["guarantee_verified"] is True

def test_chaos_competing_batch():
    """Verifies that atomic dual-order batch assignment succeeds atomically."""
    # Register 1 rider near pickup
    client.post("/riders/rider_batch_courier/register", json={"lat": 12.9720, "lon": 77.5940})

    res = client.post("/chaos/competing-batch", json={
        "order_id_1": "ord_batch_x",
        "order_id_2": "ord_batch_y",
        "center_lat": 12.9720,
        "center_lon": 77.5940,
        "radius_km": 15.0
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["assigned_rider"] == "rider_batch_courier"
    assert data["double_bookings"] == 0

def test_rich_metrics_endpoint():
    """Verifies /metrics returns rich metrics for the Operations Dashboard."""
    res = client.get("/metrics")
    assert res.status_code == 200
    m = res.json()
    assert "active_viewers" in m
    assert "pending_outbox_items" in m
    assert "db_location_writes_total" in m
    assert "updates_per_second" in m
    assert "p95_assignment_latency_ms" in m

def test_all_frontend_portals_served():
    """Verifies that all 4 frontend testbed portals are accessible."""
    portals = [
        "/static/index.html",
        "/static/restaurant.html",
        "/static/ops.html",
        "/static/chaos.html",
        "/static/js/ws.js",
        "/static/js/tracker.js",
        "/static/js/board.js",
        "/static/js/ops.js",
        "/static/js/chaos.js"
    ]
    for path in portals:
        resp = client.get(path)
        assert resp.status_code == 200, f"Failed to serve {path}"
