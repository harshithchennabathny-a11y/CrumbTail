import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from app.database import init_db
from app.main_a import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_order_creation():
    """Verifies creating an order initializes it in 'placed' state."""
    response = client.post("/orders", json={
        "customer_id": "cust_1",
        "restaurant_id": "rest_1",
        "items": ["Burger", "Fries"]
    })
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "placed"
    assert data["id"].startswith("ord_")
    assert data["rider_id"] is None

def test_valid_lifecycle_progression():
    """Happy path: placed -> accepted -> preparing -> picked_up -> delivered."""
    create_res = client.post("/orders", json={"customer_id": "c1", "restaurant_id": "r1", "items": ["Pizza"]})
    order_id = create_res.json()["id"]
    
    # 1. placed -> accepted
    res1 = client.post(f"/orders/{order_id}/status", json={"status": "accepted"})
    assert res1.status_code == 200
    assert res1.json()["status"] == "accepted"
    
    # 2. accepted -> preparing
    res2 = client.post(f"/orders/{order_id}/status", json={"status": "preparing"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "preparing"
    
    # 3. preparing -> picked_up
    res3 = client.post(f"/orders/{order_id}/status", json={"status": "picked_up"})
    assert res3.status_code == 200
    assert res3.json()["status"] == "picked_up"
    
    # 4. picked_up -> delivered
    res4 = client.post(f"/orders/{order_id}/status", json={"status": "delivered"})
    assert res4.status_code == 200
    assert res4.json()["status"] == "delivered"

def test_illegal_forward_jump_returns_409():
    """Skipping states (placed -> delivered) must return HTTP 409 Conflict."""
    create_res = client.post("/orders", json={"customer_id": "c2", "restaurant_id": "r2", "items": ["Dosa"]})
    order_id = create_res.json()["id"]
    
    bad_res = client.post(f"/orders/{order_id}/status", json={"status": "delivered"})
    assert bad_res.status_code == 409
    assert "Invalid state transition" in bad_res.json()["detail"]

def test_illegal_backward_transition_returns_409():
    """Moving backward (preparing -> placed) must return HTTP 409 Conflict."""
    create_res = client.post("/orders", json={"customer_id": "c3", "restaurant_id": "r3", "items": ["Chai"]})
    order_id = create_res.json()["id"]
    
    client.post(f"/orders/{order_id}/status", json={"status": "accepted"})
    client.post(f"/orders/{order_id}/status", json={"status": "preparing"})
    
    # Attempt backward jump
    bad_res = client.post(f"/orders/{order_id}/status", json={"status": "placed"})
    assert bad_res.status_code == 409

def test_cancellation_rules():
    """Cancellation is allowed from placed/accepted/preparing, but forbidden once delivered."""
    # Cancel from placed
    c_res1 = client.post("/orders", json={"customer_id": "c4", "restaurant_id": "r4", "items": ["Coffee"]})
    oid1 = c_res1.json()["id"]
    assert client.post(f"/orders/{oid1}/status", json={"status": "cancelled"}).status_code == 200
    
    # Complete an order to delivered
    c_res2 = client.post("/orders", json={"customer_id": "c5", "restaurant_id": "r5", "items": ["Tea"]})
    oid2 = c_res2.json()["id"]
    client.post(f"/orders/{oid2}/status", json={"status": "accepted"})
    client.post(f"/orders/{oid2}/status", json={"status": "preparing"})
    client.post(f"/orders/{oid2}/status", json={"status": "picked_up"})
    client.post(f"/orders/{oid2}/status", json={"status": "delivered"})
    
    # Attempt cancel after delivered -> 409
    assert client.post(f"/orders/{oid2}/status", json={"status": "cancelled"}).status_code == 409

def test_idempotency_key_deduplication():
    """Repeating exact request with same X-Idempotency-Key returns cached response without duplicate effects."""
    idemp_key = "unique-key-12345"
    headers = {"X-Idempotency-Key": idemp_key}
    
    res1 = client.post("/orders", json={"customer_id": "c6", "restaurant_id": "r6", "items": ["Roll"]}, headers=headers)
    assert res1.status_code == 201
    order_id_1 = res1.json()["id"]
    
    # Replay identical request 3 times
    for _ in range(3):
        res_replay = client.post("/orders", json={"customer_id": "c6", "restaurant_id": "r6", "items": ["Roll"]}, headers=headers)
        assert res_replay.status_code == 201
        assert res_replay.json()["id"] == order_id_1

