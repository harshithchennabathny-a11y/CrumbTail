"""Rider management endpoints."""
import time, json
from fastapi import APIRouter
from app.redis_client import get_sync_redis

router = APIRouter(prefix="/riders", tags=["Riders"])

@router.get("/{rider_id}/state")
async def get_rider_state(rider_id: str):
    r = get_sync_redis()
    data = r.hgetall(f"rider:{rider_id}:latest")
    if not data:
        return {"rider_id": rider_id, "found": False}
    return {
        "rider_id": rider_id, "found": True,
        "lat": float(data.get("lat", 0)),
        "lon": float(data.get("lon", 0)),
        "status": data.get("status", "free"),
        "state": data.get("state", "idle"),
        "active_order_id": data.get("active_order_id", ""),
        "active_order_id_2": data.get("active_order_id_2", ""),
    }

@router.post("/{rider_id}/register")
async def register_rider(rider_id: str, lat: float = 12.9716, lon: float = 77.5946):
    r = get_sync_redis()
    now_ts = str(int(time.time()))
    r.geoadd("riders:geo", (lon, lat, rider_id))
    r.hset(f"rider:{rider_id}:latest", mapping={
        "status": "free", "lat": str(lat), "lon": str(lon),
        "seq": "0", "active_order_id": "", "active_order_id_2": "",
        "updated_at": now_ts, "state": "idle"
    })
    r.set(f"rider:{rider_id}:seq", "0")
    return {"registered": True, "rider_id": rider_id, "lat": lat, "lon": lon}

@router.get("/available")
async def list_available():
    r = get_sync_redis()
    members = r.zrange("riders:geo", 0, -1)
    results = []
    for rid in members:
        data = r.hgetall(f"rider:{rid}:latest")
        if data:
            results.append({
                "rider_id": rid,
                "lat": float(data.get("lat", 0)),
                "lon": float(data.get("lon", 0)),
                "status": data.get("status", "free"),
                "state": data.get("state", "idle"),
            })
    return {"count": len(results), "riders": results}

@router.get("/all")
async def list_all_riders():
    """All riders with their current state — for ops map."""
    r = get_sync_redis()
    riders = []
    for key in r.scan_iter("rider:*:latest"):
        data = r.hgetall(key)
        if data:
            rid = key.replace("rider:", "").replace(":latest", "")
            riders.append({
                "rider_id": rid,
                "lat": float(data.get("lat", 0)),
                "lon": float(data.get("lon", 0)),
                "status": data.get("status", "free"),
                "state": data.get("state", "idle"),
                "active_order_id": data.get("active_order_id", ""),
            })
    return {"count": len(riders), "riders": riders}
