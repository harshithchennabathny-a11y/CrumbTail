import time
import random
import asyncio
import httpx
from app.config import NOTIFICATION_SERVICE_URL
from app.database import get_db
from app.crud import get_pending_outbox_rows, mark_outbox_sent, mark_outbox_failed_retry

def process_outbox_batch(max_batch: int = 50) -> int:
    """
    Processes one batch of pending outbox rows.
    Returns the count of successfully dispatched events.
    """
    dispatched_count = 0
    with get_db() as conn:
        pending_rows = get_pending_outbox_rows(conn, limit=max_batch)
        if not pending_rows:
            return 0
            
        with httpx.Client(timeout=2.0) as client:
            for row in pending_rows:
                outbox_id = row["id"]
                event_key = row["event_key"]
                order_id = row["order_id"]
                status_val = row["status"]
                payload_str = row["payload"]
                retries = row["retry_count"]
                
                try:
                    res = client.post(
                        NOTIFICATION_SERVICE_URL,
                        json={
                            "event_key": event_key,
                            "order_id": order_id,
                            "status": status_val,
                            "payload": payload_str
                        }
                    )
                    if res.status_code == 200:
                        mark_outbox_sent(conn, outbox_id)
                        dispatched_count += 1
                        print(f"[OUTBOX] Dispatched {event_key} -> SENT")
                    else:
                        raise httpx.HTTPError(f"HTTP {res.status_code}")
                except Exception as ex:
                    # Exponential backoff with randomized jitter
                    delay = min(30.0, (1.5 ** retries) + random.uniform(0.1, 0.5))
                    mark_outbox_failed_retry(conn, outbox_id, retries, delay)
                    print(f"[OUTBOX] Delivery failed for {event_key}: {ex}. Scheduled retry in {delay:.2f}s")
                    
    return dispatched_count

def run_worker_loop():
    """Continuous polling loop for the outbox daemon."""
    print(f"Starting Crumb Trail Transactional Outbox Worker...")
    print(f"Targeting notification endpoint: {NOTIFICATION_SERVICE_URL}")
    while True:
        try:
            count = process_outbox_batch()
            # If no items were pending, sleep 500ms
            if count == 0:
                time.sleep(0.5)
        except Exception as e:
            print(f"[OUTBOX ERROR] Worker encountered error: {e}")
            time.sleep(1.0)

if __name__ == "__main__":
    run_worker_loop()

