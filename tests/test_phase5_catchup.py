import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
import pytest
from fastapi.testclient import TestClient
from app.main_a import app as app_a
from app.database import init_db
from app.redis_client import get_sync_redis
import app.websockets as ws_module

@pytest.fixture(autouse=True)
def setup_redis():
    init_db()
    r = get_sync_redis()
    r.flushdb()
    ws_module._active_order_viewers.clear()
    ws_module._shared_listeners.clear()

def test_dynamic_shared_pubsub_subscription_and_cleanup():
    """
    Task 5.2 Verification:
    - Verifies that when the 1st viewer connects to an order, a shared listener is spawned.
    - Verifies multiple viewers on the same order share that subscription.
    - Verifies that when all viewers disconnect, the shared listener is cleanly unsubscribed.
    """
    order_id = "ord_dynamic_test_501"
    client1 = TestClient(app_a)
    client2 = TestClient(app_a)

    # 1. First viewer connects
    with client1.websocket_connect(f"/ws/orders/{order_id}") as ws1:
        time.sleep(0.05)
        assert order_id in ws_module._active_order_viewers
        assert len(ws_module._active_order_viewers[order_id]) == 1
        assert order_id in ws_module._shared_listeners

        # 2. Second viewer connects from client2 for the same order
        with client2.websocket_connect(f"/ws/orders/{order_id}") as ws2:
            time.sleep(0.05)
            assert len(ws_module._active_order_viewers[order_id]) == 2
            # Still exactly 1 shared listener
            assert len(ws_module._shared_listeners) == 1

            # 3. Publish to track:{orderId} -> both viewers must receive it
            r = get_sync_redis()
            payload = json.dumps({"type": "location", "lat": 12.9716, "lon": 77.5946, "seq": 1})
            r.publish(f"track:{order_id}", payload)

            msg1 = json.loads(ws1.receive_text())
            msg2 = json.loads(ws2.receive_text())
            assert msg1["lat"] == 12.9716
            assert msg2["lat"] == 12.9716
            
            ws2.close()

        ws1.close()

    time.sleep(0.1)
    # 4. All viewers disconnected -> shared listener must be cleaned up
    assert order_id not in ws_module._active_order_viewers
    assert order_id not in ws_module._shared_listeners

def test_high_watermark_stream_replay_catchup():
    """
    Task 5.3 & Architectural Flaw B Verification:
    - Pre-populates stream with 3 events.
    - Client connects and sends 'hello' with last_event_id.
    - Verifies client receives missed events in stream order.
    """
    order_id = "ord_stream_catchup_502"
    stream_key = f"stream:order:{order_id}"
    r = get_sync_redis()
    client = TestClient(app_a)

    id1 = r.xadd(stream_key, {"seq": "1", "lat": "12.9710", "lon": "77.5940"})
    id2 = r.xadd(stream_key, {"seq": "2", "lat": "12.9720", "lon": "77.5942"})
    id3 = r.xadd(stream_key, {"seq": "3", "lat": "12.9730", "lon": "77.5944"})

    with client.websocket_connect(f"/ws/orders/{order_id}") as ws:
        # Client requests catchup from id1
        ws.send_text(json.dumps({
            "action": "hello",
            "last_event_id": id1
        }))

        # Must receive id2 and id3
        frame1 = json.loads(ws.receive_text())
        assert frame1["type"] == "replay"
        assert frame1["event"]["seq"] == "2"

        frame2 = json.loads(ws.receive_text())
        assert frame2["type"] == "replay"
        assert frame2["event"]["seq"] == "3"

def test_distributed_redis_presence_tracking():
    """
    Architectural Flaw C Verification:
    - Verifies that active viewer counts are reflected in Redis key presence:order:{order_id}.
    """
    order_id = "ord_presence_test_503"
    r = get_sync_redis()
    client = TestClient(app_a)

    with client.websocket_connect(f"/ws/orders/{order_id}") as ws:
        time.sleep(0.05)
        key = f"presence:order:{order_id}"
        counts = r.hgetall(key)
        assert len(counts) > 0
        total = sum(int(v) for v in counts.values())
        assert total >= 1
        ws.close()

    client.close()
    time.sleep(0.05)
    counts_after = r.hgetall(key)
    total_after = sum(int(v) for v in counts_after.values()) if counts_after else 0
    assert total_after == 0
