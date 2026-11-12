import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
import pytest
from fastapi.testclient import TestClient
from app.main_a import app
from app.redis_client import get_sync_redis
from app.database import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup():
    init_db()

def test_websocket_order_tracking_and_live_pubsub():
    """Verifies that WebSocket receives live location frames pushed to track:{orderId}."""
    r = get_sync_redis()
    order_id = "ord_ws_live_1"
    rider_id = "rider_ws_live_1"
    
    # 1. Bind rider to active order in Redis
    r.hset(f"rider:{rider_id}:latest", mapping={
        "status": "busy",
        "active_order_id": order_id,
        "lat": "12.9716",
        "lon": "77.5946"
    })
    r.set(f"rider:{rider_id}:seq", "10")
    
    # 2. Connect WebSocket
    with client.websocket_connect(f"/ws/orders/{order_id}") as ws:
        # Give PubSub subscription a moment to establish
        time.sleep(0.1)
        
        # Ingest new location for rider
        res = client.post("/locations", json={
            "rider_id": rider_id,
            "lat": 12.9720,
            "lon": 77.5950,
            "seq": 11
        })
        assert res.status_code == 200
        
        # Read WebSocket message
        msg = ws.receive_text()
        data = json.loads(msg)
        assert data["type"] == "location"
        assert data["order_id"] == order_id
        assert data["rider_id"] == rider_id
        assert data["seq"] == 11
        assert data["lat"] == 12.9720

def test_stream_reconnect_replay():
    """
    CRITICAL HACKATHON TEST:
    Verifies that client sending 'hello' handshake with last_event_id
    replays missed events from Redis Stream without reloading the page.
    """
    r = get_sync_redis()
    order_id = "ord_stream_catchup"
    stream_key = f"stream:order:{order_id}"
    r.delete(stream_key)
    
    # Seed 2 events in Redis Stream
    id1 = r.xadd(stream_key, {"type": "status", "status": "accepted", "timestamp": "1000"})
    id2 = r.xadd(stream_key, {"type": "status", "status": "preparing", "timestamp": "2000"})
    
    with client.websocket_connect(f"/ws/orders/{order_id}") as ws:
        # Send hello handshake requesting events since 0
        ws.send_text(json.dumps({"action": "hello", "last_event_id": "0"}))
        
        # Receive first replayed event
        msg1 = json.loads(ws.receive_text())
        assert msg1["type"] == "replay"
        assert msg1["stream_id"] == id1
        assert msg1["event"]["status"] == "accepted"
        
        # Receive second replayed event
        msg2 = json.loads(ws.receive_text())
        assert msg2["type"] == "replay"
        assert msg2["stream_id"] == id2
        assert msg2["event"]["status"] == "preparing"
        
    print("\n[VERIFIED] WebSocket replayed missed events from Redis Stream successfully.")

def test_targeted_fanout_isolation():
    """Verifies that an update published to order A is NOT broadcast to a viewer on order B."""
    r = get_sync_redis()
    
    with client.websocket_connect("/ws/orders/ord_isolated_A") as ws_A:
        time.sleep(0.1)
        
        # Publish update to order B
        r.publish("track:ord_isolated_B", json.dumps({"type": "location", "order_id": "ord_isolated_B"}))
        
        # Publish update to order A
        r.publish("track:ord_isolated_A", json.dumps({"type": "location", "order_id": "ord_isolated_A"}))
        
        # Client A must receive message for A, not B
        msg = json.loads(ws_A.receive_text())
        assert msg["order_id"] == "ord_isolated_A"

