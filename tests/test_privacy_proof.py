"""
Privacy Proof Test (Contract Guarantee):
Verifies that the server ONLY pushes telemetry for order A's rider to order A's viewers.
Zero data leakage across customer tracking channels.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
import pytest
from fastapi.testclient import TestClient
from app.main_a import app as app_a
from app.redis_client import get_sync_redis

client = TestClient(app_a)

def test_order_channel_strict_privacy_isolation():
    """
    Subscribes to /ws/orders/order_test_privacy_A.
    Emits location updates for rider_assigned_A (on order A) AND rider_unrelated_B (on order B).
    Asserts that the WebSocket connection ONLY ever receives rider_assigned_A and NEVER rider_unrelated_B.
    """
    r = get_sync_redis()
    
    order_a = "order_test_privacy_A"
    order_b = "order_test_privacy_B"
    rider_a = "rider_assigned_A"
    rider_b = "rider_unrelated_B"
    
    # 1. Setup Redis state: order A has rider A; order B has rider B
    r.hset(f"order:{order_a}", mapping={"id": order_a, "rider_id": rider_a, "status": "accepted"})
    r.hset(f"rider:{rider_a}:latest", mapping={"status": "busy", "active_order_id": order_a, "lat": "12.9716", "lon": "77.5946"})
    r.set(f"rider:{rider_a}:seq", "200")
    
    r.hset(f"order:{order_b}", mapping={"id": order_b, "rider_id": rider_b, "status": "accepted"})
    r.hset(f"rider:{rider_b}:latest", mapping={"status": "busy", "active_order_id": order_b, "lat": "12.9352", "lon": "77.6245"})
    r.set(f"rider:{rider_b}:seq", "200")
    
    # 2. Open WebSocket connection strictly for Order A
    with client.websocket_connect(f"/ws/orders/{order_a}") as ws:
        time.sleep(0.15)  # Allow Pub/Sub subscription to attach
        
        # Ingest location for Rider B (Order B) -> Should NOT arrive on Order A's socket
        res_b = client.post("/locations", json={
            "rider_id": rider_b,
            "lat": 12.9355,
            "lon": 77.6250,
            "seq": 201
        })
        assert res_b.status_code == 200
        
        # Ingest location for Rider A (Order A) -> MUST arrive on Order A's socket
        res_a = client.post("/locations", json={
            "rider_id": rider_a,
            "lat": 12.9720,
            "lon": 77.5950,
            "seq": 201
        })
        assert res_a.status_code == 200
        
        # Receive frame on Order A's WebSocket
        msg_text = ws.receive_text()
        msg_data = json.loads(msg_text)
        
        # Privacy Invariant: Received message MUST belong to Rider A and Order A
        assert msg_data.get("rider_id") == rider_a, f"Privacy Leak! Expected {rider_a}, received {msg_data.get('rider_id')}"
        assert msg_data.get("order_id") == order_a
        
        # Ping check proves no extraneous rider B frame was queued
        ws.send_text(json.dumps({"action": "ping", "ts": 9999}))
        pong = json.loads(ws.receive_text())
        assert pong.get("type") == "pong"
        
    print("\n[PRIVACY PROOF OK] Zero cross-channel leakage confirmed.")
