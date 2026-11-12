import time
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Response, status, HTTPException
from app.models import LocationIngest
from app.redis_client import (
    get_sync_redis,
    ingest_location_atomic,
    check_rate_limit_atomic
)
from app.location_sampler import record_location_sample

router = APIRouter(tags=["Locations & GPS Ingestion"])

@router.post("/locations")
async def ingest_location(loc: LocationIngest, response: Response):
    """
    Ingests 1 Hz rider GPS ping with monotonic sequence verification.
    - Rate limits flooding devices via Redis sliding window (HTTP 429).
    - Drops stale/duplicate packets (seq <= stored_seq) via atomic Lua script.
    - Downsamples active coordinates for bulk SQLite persistence (< 50 writes/s).
    """
    # 1. Sliding window rate limit check
    device_key = loc.device_id or f"device:{loc.rider_id}"
    is_allowed = check_rate_limit_atomic(identifier=device_key, window_ms=1000, max_requests=25)
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for device '{device_key}'. Max 25 pings/sec."
        )

    # 2. Atomic Ingestion Lua script execution
    now_ts = loc.timestamp if loc.timestamp is not None else int(time.time())
    accepted = ingest_location_atomic(
        rider_id=loc.rider_id,
        incoming_seq=loc.seq,
        lat=loc.lat,
        lon=loc.lon,
        timestamp=now_ts
    )

    if accepted == 0:
        # Dropped: stale or duplicate packet
        return {
            "accepted": False,
            "rider_id": loc.rider_id,
            "seq": loc.seq,
            "reason": "stale_or_duplicate_seq"
        }

    # 3. Sample for batched SQLite persistence
    record_location_sample(loc.rider_id, loc.lat, loc.lon, loc.seq)

    # 4. Record throughput metric for live ops dashboard
    try:
        r = get_sync_redis()
        now_sec = int(time.time())
        mkey = f"metrics:updates:{now_sec}"
        r.incr(mkey)
        r.expire(mkey, 10)
    except Exception:
        pass

    return {
        "accepted": True,
        "rider_id": loc.rider_id,
        "seq": loc.seq
    }

@router.get("/riders/available")
async def list_available_riders():
    """Returns list of online riders currently available in Redis geospatial index."""
    r = get_sync_redis()
    # Read all members in riders:geo
    members = r.zrange("riders:geo", 0, -1)
    results = []
    for rider_id in members:
        pos = r.geopos("riders:geo", rider_id)
        if pos and pos[0]:
            lon, lat = pos[0]
            results.append({"rider_id": rider_id, "lat": lat, "lon": lon, "status": "free"})
    return {"count": len(results), "riders": results}

@router.post("/riders/{rider_id}/register")
async def register_rider(rider_id: str, lat: float = 12.9716, lon: float = 77.5946):
    """Initializes or resets a free rider at specified coordinates."""
    r = get_sync_redis()
    now_ts = str(int(time.time()))
    r.geoadd("riders:geo", (lon, lat, rider_id))
    r.hset(f"rider:{rider_id}:latest", mapping={
        "status": "free",
        "lat": str(lat),
        "lon": str(lon),
        "seq": "0",
        "active_order_id": "",
        "updated_at": now_ts
    })
    r.set(f"rider:{rider_id}:seq", "0")
    return {"registered": True, "rider_id": rider_id, "lat": lat, "lon": lon, "status": "free"}
