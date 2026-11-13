import redis
import redis.asyncio as aioredis
import time
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_SCRIPTS_DIR

REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Thread-safe synchronous client (pool managed by redis-py)
_sync_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    socket_timeout=2.0,
    socket_connect_timeout=2.0
)

# Cache loaded Lua scripts
_lua_cache = {}

def get_lua_script(name: str) -> str:
    """Reads Lua script from disk."""
    if name not in _lua_cache:
        path = REDIS_SCRIPTS_DIR / f"{name}.lua"
        if not path.exists():
            raise FileNotFoundError(f"Lua script '{name}.lua' not found at {path}")
        _lua_cache[name] = path.read_text(encoding="utf-8")
    return _lua_cache[name]

def assign_rider_atomic(lon: float, lat: float, order_id: str, radius_km: float = 5.0) -> Optional[str]:
    """
    Executes assign_rider.lua atomically.
    Returns assigned rider_id, or None if no candidate free.
    """
    client = get_sync_redis()
    script = get_lua_script("assign_rider")
    now_ts = str(int(time.time()))
    keys = ["riders:geo", f"order:{order_id}"]
    args = [str(lon), str(lat), str(radius_km), order_id, now_ts]
    return client.eval(script, len(keys), *keys, *args)

def claim_rider_atomic(rider_id: str, order_id: str) -> Optional[str]:
    """Claims a specific rider atomically via claim_rider.lua."""
    client = get_sync_redis()
    script = get_lua_script("claim_rider")
    now_ts = str(int(time.time()))
    keys = ["riders:geo", f"order:{order_id}"]
    args = [rider_id, order_id, now_ts]
    return client.eval(script, len(keys), *keys, *args)

def assign_rider_with_astar(lon: float, lat: float, order_id: str, radius_km: float = 8.0) -> Optional[str]:
    """
    Rider selection:
    1. GEOSEARCH returns K=5-8 nearest candidates by straight-line distance (<50 ms target).
    2. A* computes road ETA from rider location to pickup for each candidate.
    3. Lowest ETA candidate is claimed atomically; if race lost, next candidate is tried.
    """
    client = get_sync_redis()
    t0 = time.time()
    
    # Fast straight-line geospatial search (< 50ms)
    try:
        candidates = client.geosearch(
            "riders:geo",
            longitude=lon,
            latitude=lat,
            radius=radius_km,
            unit="km",
            sort="ASC",
            count=8
        )
    except Exception:
        return assign_rider_atomic(lon=lon, lat=lat, order_id=order_id, radius_km=radius_km)
        
    geo_ms = (time.time() - t0) * 1000
    try:
        client.lpush("metrics:geo_latency_ms", str(geo_ms))
        client.ltrim("metrics:geo_latency_ms", 0, 99)
    except Exception:
        pass

    if not candidates:
        return None

    # Step 2: Road ETA scoring via A*
    try:
        from app.routing.astar import compute_road_eta_sec
        candidate_etas = []
        for rid in candidates:
            pos = client.hmget(f"rider:{rid}:latest", "lat", "lon", "status")
            if pos and pos[0] and pos[1] and (pos[2] or "free") == "free":
                rlat, rlon = float(pos[0]), float(pos[1])
                eta_sec = compute_road_eta_sec(rlat, rlon, lat, lon)
                candidate_etas.append((eta_sec, rid))

        candidate_etas.sort(key=lambda x: x[0])

        # Step 3: Atomic claim in order of lowest ETA
        for _, rid in candidate_etas:
            claimed = claim_rider_atomic(rid, order_id)
            if claimed:
                return claimed
    except Exception:
        pass

    # Fallback to direct Lua assignment
    return assign_rider_atomic(lon=lon, lat=lat, order_id=order_id, radius_km=radius_km)

def assign_batch_atomic(lon: float, lat: float, order_id_1: str, order_id_2: str, radius_km: float = 5.0) -> Optional[str]:
    """
    Executes assign_batch.lua atomically for 2 orders competing for 1 rider.
    Returns assigned rider_id, or None if no candidate free.
    """
    client = get_sync_redis()
    script = get_lua_script("assign_batch")
    now_ts = str(int(time.time()))
    keys = ["riders:geo", f"order:{order_id_1}", f"order:{order_id_2}"]
    args = [str(lon), str(lat), str(radius_km), order_id_1, order_id_2, now_ts]
    return client.eval(script, len(keys), *keys, *args)

def ingest_location_atomic(rider_id: str, incoming_seq: int, lat: float, lon: float, timestamp: Optional[int] = None) -> int:
    """
    Executes ingest_location.lua atomically.
    Returns 1 if accepted, 0 if duplicate/stale packet dropped.
    """
    client = get_sync_redis()
    script = get_lua_script("ingest_location")
    ts = str(timestamp if timestamp is not None else int(time.time()))
    keys = [
        f"rider:{rider_id}:seq",
        f"rider:{rider_id}:latest",
        "riders:geo"
    ]
    args = [rider_id, str(incoming_seq), str(lat), str(lon), ts]
    return int(client.eval(script, len(keys), *keys, *args))

def release_rider(rider_id: str) -> bool:
    """
    Frees a rider and re-adds them to the active geospatial index upon delivery/cancellation.
    """
    try:
        client = get_sync_redis()
        r_key = f"rider:{rider_id}:latest"
        client.hset(r_key, mapping={
            "status": "free",
            "active_order_id": "",
            "active_order_id_2": "",
            "updated_at": str(time.time())
        })
        pos = client.hmget(r_key, "lat", "lon")
        if pos and pos[0] and pos[1]:
            client.geoadd("riders:geo", (float(pos[1]), float(pos[0]), rider_id))
        return True
    except Exception as e:
        print(f"[REDIS WARN] Failed to release rider {rider_id}: {e}")
        return False

def check_rate_limit_atomic(identifier: str, window_ms: int = 1000, max_requests: int = 30) -> bool:
    """
    Executes rate_limiter.lua sliding-window check.
    Returns True if allowed, False if rate limited.
    """
    client = get_sync_redis()
    script = get_lua_script("rate_limiter")
    now_ms = str(int(time.time() * 1000))
    keys = [f"ratelimit:{identifier}"]
    args = [now_ms, str(window_ms), str(max_requests)]
    res = client.eval(script, len(keys), *keys, *args)
    return bool(res == 1)

def get_sync_redis() -> redis.Redis:
    """Returns a thread-safe synchronous Redis client instance."""
    return _sync_client

def get_async_redis() -> aioredis.Redis:
    """Returns an asynchronous Redis client instance bound to the current event loop."""
    return aioredis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_timeout=2.0,
        socket_connect_timeout=2.0
    )

def check_redis() -> bool:
    """
    Safely pings Redis synchronously.
    Returns True if responsive, False if down/disconnected.
    """
    try:
        return bool(_sync_client.ping())
    except Exception:
        return False

async def check_async_redis() -> bool:
    """
    Safely pings Redis asynchronously.
    Returns True if responsive, False if down/disconnected.
    """
    client = get_async_redis()
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()
