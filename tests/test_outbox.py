import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pytest
from fastapi.testclient import TestClient
from app.database import init_db, get_db
from app.main_a import app as app_a
from app.mock_notification_service import app as notif_app
from app.crud import get_pending_outbox_rows, mark_outbox_sent
import app.outbox_worker as outbox_worker

client_api = TestClient(app_a)
client_notif = TestClient(notif_app)

@pytest.fixture(autouse=True)
def setup():
    init_db()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM outbox;")
        cursor.execute("DELETE FROM processed_notifications;")
        cursor.close()

def test_outbox_row_committed_with_status_change():
    """Verifies that an outbox row is created inside the same transaction as status transition."""
    # Place order
    res = client_api.post("/orders", json={"customer_id": "c_outbox", "restaurant_id": "r_outbox", "items": ["Noodles"]})
    order_id = res.json()["id"]
    
    # Transition to accepted
    client_api.post(f"/orders/{order_id}/status", json={"status": "accepted"})
    
    # Verify outbox table has pending row for this order
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT event_key, order_id, status, state FROM outbox WHERE order_id = ? AND status = 'accepted';", (order_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == f"{order_id}:accepted"
        assert row[1] == order_id
        assert row[2] == "accepted"
        assert row[3] == "pending"
        cursor.close()

def test_mock_notification_service_idempotency():
    """Verifies that mock notification service on port 9000 deduplicates repeated keys."""
    event_key = "ord_test_999:accepted"
    payload = json.dumps({"order_id": "ord_test_999", "status": "accepted"})
    
    # 1. First delivery -> Delivered
    res1 = client_notif.post("/notify", json={
        "event_key": event_key,
        "order_id": "ord_test_999",
        "status": "accepted",
        "payload": payload
    })
    assert res1.status_code == 200
    assert res1.json()["status"] == "delivered"
    
    # 2. Second delivery of exact same event_key -> Detected as Duplicate and Ignored
    res2 = client_notif.post("/notify", json={
        "event_key": event_key,
        "order_id": "ord_test_999",
        "status": "accepted",
        "payload": payload
    })
    assert res2.status_code == 200
    assert res2.json()["status"] == "already_processed"
    print("\n[VERIFIED] Notification service ignored duplicate delivery via persistent processed ledger.")

def test_outbox_dispatch_end_to_end(monkeypatch):
    """Verifies outbox_worker processes pending rows, dispatches, and updates state to sent."""
    # Place and update order
    res = client_api.post("/orders", json={"customer_id": "c_worker", "restaurant_id": "r_worker", "items": ["Biryani"]})
    order_id = res.json()["id"]
    client_api.post(f"/orders/{order_id}/status", json={"status": "accepted"})
    
    # Mock httpx response to avoid TestClient recursion
    class MockPostResponse:
        status_code = 200
        def json(self):
            return {"status": "delivered"}
            
    monkeypatch.setattr(outbox_worker.httpx.Client, "post", lambda self, url, json=None, **kwargs: MockPostResponse())
    
    # Process batch
    dispatched = outbox_worker.process_outbox_batch()
    assert dispatched >= 1
    
    # Verify row marked sent
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state, sent_at FROM outbox WHERE order_id = ? AND status = 'accepted';", (order_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "sent"
        assert row[1] is not None
        cursor.close()
