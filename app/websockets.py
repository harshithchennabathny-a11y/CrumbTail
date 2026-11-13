import json
import asyncio
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.redis_client import get_sync_redis, get_async_redis
from app.config import INSTANCE_ID

router = APIRouter(tags=["WebSockets"])

# Local connection registry: order_id -> set of active WebSockets
_active_order_viewers: Dict[str, Set[WebSocket]] = {}
_ops_viewers: Set[WebSocket] = set()
_board_viewers: Set[WebSocket] = set()

# Shared background listener tasks per channel: channel_name -> Task
_shared_listeners: Dict[str, asyncio.Task] = {}

def get_total_viewers_count() -> int:
    """Returns count of active WebSocket viewers across all local connections."""
    return sum(len(conns) for conns in _active_order_viewers.values()) + len(_ops_viewers) + len(_board_viewers)

def update_redis_presence_sync(order_id: str, delta: int):
    """
    Synchronously updates cluster-wide presence in Redis.
    Immune to async event loop cancellations during socket disconnects.
    Hash key: presence:order:{order_id}
    Field: instance_id -> count
    """
    try:
        r = get_sync_redis()
        field = f"instance_{INSTANCE_ID}"
        key = f"presence:order:{order_id}"
        new_val = r.hincrby(key, field, delta)
        if new_val <= 0:
            r.hdel(key, field)
        else:
            r.expire(key, 120)  # 2-minute rolling TTL
    except Exception as e:
        print(f"[PRESENCE ERROR]: {e}")

def get_global_order_viewers(order_id: str) -> int:
    """Returns total active viewers for an order across ALL FastAPI instances."""
    try:
        r = get_sync_redis()
        key = f"presence:order:{order_id}"
        all_counts = r.hgetall(key)
        return sum(int(v) for v in all_counts.values()) if all_counts else 0
    except Exception:
        return len(_active_order_viewers.get(order_id, []))

async def _start_shared_order_listener(order_id: str):
    """
    Dynamic Pub/Sub Listener (Handbook Task 5.2):
    Subscribes to Redis Pub/Sub channel 'track:{orderId}' ONLY when the
    first viewer arrives, and multiplexes frames to all local WebSockets.
    """
    channel_name = f"track:{order_id}"
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel_name)

    async def _listener_loop():
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    raw_data = message["data"]
                    # Fan out to all local viewers for this order
                    viewers = list(_active_order_viewers.get(order_id, []))
                    dead_sockets = []
                    for ws in viewers:
                        try:
                            await ws.send_text(raw_data)
                        except Exception:
                            dead_sockets.append(ws)
                    for ds in dead_sockets:
                        _active_order_viewers.get(order_id, set()).discard(ds)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(channel_name)
                await pubsub.aclose()
                await r.aclose()
            except Exception:
                pass

    task = asyncio.create_task(_listener_loop())
    _shared_listeners[order_id] = task

def _stop_shared_order_listener(order_id: str):
    """Cancels shared Pub/Sub listener when the last viewer disconnects."""
    task = _shared_listeners.pop(order_id, None)
    if task:
        task.cancel()

@router.websocket("/ws/orders/{order_id}")
async def order_tracking_ws(websocket: WebSocket, order_id: str):
    """
    Real-time WebSocket endpoint for customer live tracking page.
    1. Dynamic Shared Pub/Sub: Subscribes on 1st viewer; unsubscribes on last viewer.
    2. Distributed Presence: Updates presence in Redis across Instance A and B.
    3. Race-Free Replay Protocol: Client sends 'hello' with last_event_id;
       captures high-watermark, replays missed frames from Redis Stream, then switches to live.
    """
    await websocket.accept()

    # Register local connection
    is_first_viewer = False
    if order_id not in _active_order_viewers:
        _active_order_viewers[order_id] = set()
        is_first_viewer = True
    
    _active_order_viewers[order_id].add(websocket)
    
    # 1. First viewer on this instance triggers shared subscription to Redis Pub/Sub
    if is_first_viewer or order_id not in _shared_listeners:
        await _start_shared_order_listener(order_id)

    # 2. Update cluster-wide presence in Redis synchronously
    update_redis_presence_sync(order_id, delta=1)

    r = get_async_redis()

    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                action = data.get("action")
                
                # Race-Free High-Watermark Reconnect Protocol (Reviewer Critical Flaw B)
                if action == "hello":
                    last_event_id = data.get("last_event_id")
                    if last_event_id:
                        stream_key = f"stream:order:{order_id}"
                        min_id = f"({last_event_id}" if last_event_id not in ("0", "-", "0-0") else "-"
                        try:
                            # 1. Fetch current stream high-watermark
                            info = await r.xinfo_stream(stream_key) if await r.exists(stream_key) else None
                            max_watermark = info.get("last-generated-id", "+") if info else "+"
                            
                            # 2. Replay all events between last_event_id and high-watermark
                            missed = await r.xrange(stream_key, min=min_id, max=max_watermark)
                            for stream_id, fields in missed:
                                await websocket.send_text(json.dumps({
                                    "type": "replay",
                                    "stream_id": stream_id,
                                    "event": fields
                                }))
                        except Exception as e:
                            print(f"[REPLAY ERROR] Failed to fetch stream events: {e}")

                elif action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong", "ts": data.get("ts")}))
                            
            except json.JSONDecodeError:
                pass
                
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        # Deregister local viewer
        if order_id in _active_order_viewers:
            _active_order_viewers[order_id].discard(websocket)
            if not _active_order_viewers[order_id]:
                _active_order_viewers.pop(order_id, None)
                # Last viewer on this instance: tear down shared listener
                _stop_shared_order_listener(order_id)

        # Decrement cluster-wide presence synchronously
        update_redis_presence_sync(order_id, delta=-1)
        try:
            await r.aclose()
        except Exception:
            pass

@router.websocket("/ws/restaurant")
async def restaurant_board_ws(websocket: WebSocket):
    """Real-time push for restaurant order board (listens to 'board:orders')."""
    await websocket.accept()
    _board_viewers.add(websocket)
    
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe("board:orders")
    
    forward_task = None
    async def listen_board():
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    await websocket.send_text(msg["data"])
        except (asyncio.CancelledError, Exception):
            pass

    try:
        forward_task = asyncio.create_task(listen_board())
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if forward_task:
            forward_task.cancel()
        try:
            await pubsub.unsubscribe("board:orders")
            await pubsub.aclose()
            await r.aclose()
        except Exception:
            pass
        _board_viewers.discard(websocket)

@router.websocket("/ws/ops")
async def operations_ws(websocket: WebSocket):
    """Real-time push for operations dashboard (all rider coordinates & board events)."""
    await websocket.accept()
    _ops_viewers.add(websocket)
    
    r = get_async_redis()
    pubsub = r.pubsub()
    await pubsub.psubscribe("track:*", "board:orders")
    
    forward_task = None
    async def listen_ops():
        try:
            async for msg in pubsub.listen():
                if msg["type"] in ("message", "pmessage"):
                    await websocket.send_text(msg["data"])
        except (asyncio.CancelledError, Exception):
            pass

    try:
        forward_task = asyncio.create_task(listen_ops())
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if forward_task:
            forward_task.cancel()
        try:
            await pubsub.punsubscribe("track:*", "board:orders")
            await pubsub.aclose()
            await r.aclose()
        except Exception:
            pass
        _ops_viewers.discard(websocket)

@router.websocket("/ws/ops-riders")
async def ops_riders_ws(websocket: WebSocket):
    """Streams batched rider snapshots every 500ms for the ops map canvas."""
    await websocket.accept()
    r_async = get_async_redis()
    try:
        while True:
            # Read all rider latest states
            riders = []
            # Use scan to get all rider:*:latest keys
            async for key in r_async.scan_iter("rider:*:latest"):
                data = await r_async.hgetall(key)
                if data:
                    rid = key.replace("rider:", "").replace(":latest", "")
                    try:
                        riders.append({
                            "rider_id": rid,
                            "lat": float(data.get("lat", 0)),
                            "lon": float(data.get("lon", 0)),
                            "state": data.get("state", "idle"),
                            "status": data.get("status", "free"),
                            "active_order_id": data.get("active_order_id", ""),
                        })
                    except (ValueError, TypeError):
                        pass
            await websocket.send_text(json.dumps({"type": "riders_snapshot", "riders": riders}))
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        try:
            await r_async.aclose()
        except Exception:
            pass
