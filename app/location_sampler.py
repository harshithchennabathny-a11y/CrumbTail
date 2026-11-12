import time
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone
from app.database import get_db

# Memory cache tracking when each rider was last persisted to SQLite
_last_persisted_time: Dict[str, float] = {}

# Batch buffer for downsampled location points
_pending_batch: List[Tuple[str, Optional[str], float, float, int, str]] = []

def record_location_sample(rider_id: str, lat: float, lon: float, seq: int, order_id: Optional[str] = None) -> bool:
    """
    Downsamples incoming 1 Hz GPS coordinates to 1 point per minute per rider.
    Appends to in-memory batch buffer for bulk insertion.
    Returns True if sampled, False if skipped.
    """
    now = time.time()
    last_saved = _last_persisted_time.get(rider_id, 0.0)
    
    # Only sample if 60 seconds have elapsed since last DB persist for this rider
    if (now - last_saved) >= 60.0:
        _last_persisted_time[rider_id] = now
        now_iso = datetime.now(timezone.utc).isoformat()
        _pending_batch.append((rider_id, order_id, lat, lon, seq, now_iso))
        
        # Flush if batch reaches 50 items
        if len(_pending_batch) >= 50:
            flush_location_batch()
        return True
        
    return False

def flush_location_batch() -> int:
    """
    Performs a single bulk-insert transaction to SQLite location_history table.
    Keeps database write transactions far below 50 writes/second.
    Returns number of rows persisted.
    """
    global _pending_batch
    if not _pending_batch:
        return 0
        
    batch_to_write = _pending_batch
    _pending_batch = []
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO location_history (rider_id, order_id, latitude, longitude, seq, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, batch_to_write)
            cursor.close()
        return len(batch_to_write)
    except Exception as e:
        print(f"[LOCATION SAMPLER ERROR] Bulk insert failed: {e}")
        return 0

