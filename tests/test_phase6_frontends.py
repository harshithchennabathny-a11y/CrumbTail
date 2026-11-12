import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
from starlette.testclient import TestClient
from app.main_a import app as app_a
from app.main_b import app as app_b
from app.redis_client import get_sync_redis

client_a = TestClient(app_a)
client_b = TestClient(app_b)

def test_phase6_all_dashboards_served_on_both_instances():
    """Verifies all 4 dashboards and assets are served on both Instance A and Instance B."""
    dashboards = [
        ("/static/index.html", "Crumb Tail — Live Customer Tracking"),
        ("/static/restaurant.html", "Crumb Tail — Restaurant Order Kanban"),
        ("/static/ops.html", "Crumb Tail — Operations Map & 2,000 Rider Radar"),
        ("/static/chaos.html", "Crumb Tail — Chaos Engineering & Adversarial Testbed")
    ]
    
    for path, title in dashboards:
        res_a = client_a.get(path)
        assert res_a.status_code == 200, f"Instance A failed to serve {path}"
        assert title in res_a.text, f"Title '{title}' missing in Instance A {path}"
        
        res_b = client_b.get(path)
        assert res_b.status_code == 200, f"Instance B failed to serve {path}"
        assert title in res_b.text, f"Title '{title}' missing in Instance B {path}"

def test_phase6_javascript_core_modules_integrity():
    """Verifies all static JS modules exist and contain vital real-time functions."""
    scripts = [
        ("/static/js/ws.js", ["CrumbTailWebSocket", "handleFailover", "lastEventId"]),
        ("/static/js/tracker.js", ["animateMarker", "setRiderTargetCoordinates", "setupOrder"]),
        ("/static/js/board.js", ["handleDragStart", "handleBoardEvent", "updateCounts"]),
        ("/static/js/ops.js", ["latLonToCanvas", "drawRadar", "renderLoop", "startMetricsLoop"]),
        ("/static/js/chaos.js", ["bindChaosButtons", "logToConsole"])
    ]

    for path, expected_tokens in scripts:
        res = client_a.get(path)
        assert res.status_code == 200, f"Failed to fetch {path}"
        for token in expected_tokens:
            assert token in res.text, f"Missing token '{token}' in {path}"

def test_phase6_restaurant_kanban_flow_and_409_shake():
    """
    Simulates Restaurant Kanban flow:
    1. Creates order via Instance A
    2. Moves placed -> accepted -> preparing
    3. Tries illegal transition preparing -> placed (expects 409 Conflict rollback)
    """
    # 1. Create order
    create_res = client_a.post("/orders", json={
        "customer_id": "cust_kanban_test",
        "restaurant_id": "rest_kanban_hub"
    })
    assert create_res.status_code == 201
    order_id = create_res.json()["id"]

    # 2. Advance to accepted via Instance B
    acc_res = client_b.post(f"/orders/{order_id}/status", json={"status": "accepted"})
    assert acc_res.status_code == 200
    assert acc_res.json()["status"] == "accepted"

    # 3. Advance to preparing via Instance A
    prep_res = client_a.post(f"/orders/{order_id}/status", json={"status": "preparing"})
    assert prep_res.status_code == 200
    assert prep_res.json()["status"] == "preparing"

    # 4. Attempt illegal reverse transition (preparing -> placed) -> Expect 409 Conflict
    illegal_res = client_b.post(f"/orders/{order_id}/status", json={"status": "placed"})
    assert illegal_res.status_code == 409, "Illegal backward transition must return 409 Conflict"

def test_phase6_customer_tracking_and_monotonic_guard():
    """
    Simulates Customer Tracker live updates:
    - Normal sequence increases: accepted
    - Stale sequence: rejected
    """
    rider_id = "rider_tracker_test"
    reg_res = client_a.post(f"/riders/{rider_id}/register", json={"lat": 12.9716, "lon": 77.5946})
    assert reg_res.status_code == 200

    # Ingest seq=100
    p1 = client_a.post("/locations", json={
        "rider_id": rider_id,
        "lat": 12.9718,
        "lon": 77.5948,
        "seq": 100
    })
    assert p1.status_code == 200

    # Ingest seq=95 (stale -> packet dropped)
    p2 = client_b.post("/chaos/inject-gps", json={
        "rider_id": rider_id,
        "latitude": 12.9715,
        "longitude": 77.5945,
        "seq": 95
    })
    assert p2.status_code == 200
    assert p2.json()["status"] == "rejected"

def test_phase6_chaos_console_endpoints_guarantees():
    """Verifies all chaos strike triggers exposed to the Chaos Engine."""
    # Chaos 1: Stale GPS
    res1 = client_a.post("/chaos/inject-gps", json={
        "rider_id": "rider_chaos_probe",
        "latitude": 12.97,
        "longitude": 77.59,
        "seq": 1
    })
    assert res1.status_code == 200

    # Chaos 2: Race Hammer Burst
    res2 = client_a.post("/chaos/burst-orders", json={
        "num_orders": 10,
        "latitude": 12.9716,
        "longitude": 77.5946
    })
    assert res2.status_code == 200
    assert res2.json()["double_bookings"] == 0
    assert res2.json()["guarantee_verified"] is True

    # Chaos 3: Competing Batch Assignment
    client_a.post("/riders/rider_batch_test/register", json={"lat": 12.9720, "lon": 77.5940})
    res3 = client_a.post("/chaos/competing-batch", json={
        "order_id_1": "order_test_a",
        "order_id_2": "order_test_b",
        "center_lat": 12.9720,
        "center_lon": 77.5940,
        "radius_km": 5.0
    })
    assert res3.status_code == 200

    # Chaos 4: Check Notifications
    res4 = client_a.post("/chaos/check-notifications")
    assert res4.status_code == 200
    assert "service_status" in res4.json()

    # Chaos 6: Degraded Health
    health_res = client_a.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] in ["healthy", "degraded"]
