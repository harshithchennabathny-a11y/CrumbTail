import redis
import redis.asyncio as aioredis
import time
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
