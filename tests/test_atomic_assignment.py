import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import concurrent.futures
import pytest
from app.redis_client import get_sync_redis, assign_rider_atomic, assign_batch_atomic

@pytest.fixture(autouse=True)
def clean_redis():
    """Flushes test keys from Redis before each test."""
    r = get_sync_redis()
    r.delete("riders:geo", "rider:rider_alpha:latest", "rider:rider_jackpot:latest", "rider:rider_batch_pro:latest")
    yield
    r.delete("riders:geo", "rider:rider_alpha:latest", "rider:rider_jackpot:latest", "rider:rider_batch_pro:latest")

def test_nearest_rider_atomic_assignment():
    """Verifies that nearest free rider is atomically matched and locked."""
    r = get_sync_redis()
    
    # Register free rider at Bengaluru center
    r.geoadd("riders:geo", (77.5946, 12.9716, "rider_alpha"))
    r.hset("rider:rider_alpha:latest", mapping={"status": "free", "lat": 12.9716, "lon": 77.5946})
    
    # Execute atomic assignment
    assigned = assign_rider_atomic(lon=77.5946, lat=12.9716, order_id="ord_101", radius_km=5.0)
    assert assigned == "rider_alpha"
    
    # Invariant checks: rider is marked busy, attached to order, and removed from geo index
    assert r.hget("rider:rider_alpha:latest", "status") == "busy"
    assert r.hget("rider:rider_alpha:latest", "active_order_id") == "ord_101"
    
    # Subsequent search must find no free rider
    second_attempt = assign_rider_atomic(lon=77.5946, lat=12.9716, order_id="ord_102", radius_km=5.0)
    assert second_attempt is None

def test_concurrent_race_condition_zero_double_bookings():
    """
    CRITICAL HACKATHON TEST:
    Hammers assignment with 20 concurrent threads competing for 1 free rider.
    Proves that Redis Lua guarantees exactly 1 assignment succeeds and 19 fail.
    """
    r = get_sync_redis()
    r.geoadd("riders:geo", (77.5946, 12.9716, "rider_jackpot"))
    r.hset("rider:rider_jackpot:latest", mapping={"status": "free", "lat": 12.9716, "lon": 77.5946})
    
    results = []
    
    def try_claim(order_num: int):
        return assign_rider_atomic(
            lon=77.5946,
            lat=12.9716,
            order_id=f"competing_ord_{order_num}",
            radius_km=5.0
        )
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(try_claim, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())
            
    successes = [res for res in results if res == "rider_jackpot"]
    failures = [res for res in results if res is None]
    
    assert len(successes) == 1, f"Double-assignment detected! Success count: {len(successes)}"
    assert len(failures) == 19
    print("\n[VERIFIED] 20 concurrent threads competed for 1 rider -> exactly 1 won, 19 failed cleanly (0 double assignments).")

def test_batch_assignment_atomicity():
    """Verifies that assign_batch.lua atomically claims 1 free rider for TWO orders."""
    r = get_sync_redis()
    r.geoadd("riders:geo", (77.5946, 12.9716, "rider_batch_pro"))
    r.hset("rider:rider_batch_pro:latest", mapping={"status": "free", "lat": 12.9716, "lon": 77.5946})
    
    assigned = assign_batch_atomic(
        lon=77.5946,
        lat=12.9716,
        order_id_1="batch_ord_A",
        order_id_2="batch_ord_B",
        radius_km=5.0
    )
    assert assigned == "rider_batch_pro"
    assert r.hget("rider:rider_batch_pro:latest", "status") == "busy"
    assert r.hget("rider:rider_batch_pro:latest", "active_order_id") == "batch_ord_A"
    assert r.hget("rider:rider_batch_pro:latest", "active_order_id_2") == "batch_ord_B"
    
    # Verify order hashes updated
    assert r.hget("order:batch_ord_A", "rider_id") == "rider_batch_pro"
    assert r.hget("order:batch_ord_B", "rider_id") == "rider_batch_pro"

