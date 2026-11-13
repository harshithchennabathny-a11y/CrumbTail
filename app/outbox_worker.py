import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import random
import asyncio
import httpx
from app.config import NOTIFICATION_SERVICE_URL
from app.database import get_db
from app.crud import claim_outbox_batch, mark_outbox_sent, mark_outbox_failed_retry

def process_outbox_batch(max_batch: int = 50) -> int:
    """
    Processes one batch of pending outbox rows without holding DB connections open across network calls.
    1. Atomically claim pending rows ('pending' -> 'processing') and close connection.
    2. Dispatch via HTTP to notification service.
    3. Bulk update sent/failed rows in a rapid commit.
    """
    with get_db() as conn:
        pending_rows = claim_outbox_batch(conn, limit=max_batch)
        
    if not pending_rows:
        return 0

    dispatched = []
    failed = []

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
                    dispatched.append(outbox_id)
                    print(f"[OUTBOX] Dispatched {event_key} -> SENT")
                else:
                    failed.append((outbox_id, retries, f"HTTP {res.status_code}"))
            except Exception as ex:
                failed.append((outbox_id, retries, str(ex)))

    with get_db() as conn:
        for outbox_id in dispatched:
            mark_outbox_sent(conn, outbox_id)
        for outbox_id, retries, err_msg in failed:
            delay = min(30.0, (1.5 ** retries) + random.uniform(0.1, 0.5))
            mark_outbox_failed_retry(conn, outbox_id, retries, delay)
            print(f"[OUTBOX] Delivery failed for id {outbox_id}: {err_msg}. Retry in {delay:.2f}s")

    return len(dispatched)

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

