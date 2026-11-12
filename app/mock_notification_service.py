import json
from datetime import datetime, timezone
from typing import List, Dict, Any
from fastapi import FastAPI, Request, Response, status
from pydantic import BaseModel
import uvicorn
from app.database import get_db

app = FastAPI(
    title="Crumb Trail - Notification Service (Mock)",
    description="Standalone notification service running on port 9000 with persistent idempotency ledger."
)

class NotificationRequest(BaseModel):
    event_key: str
    order_id: str
    status: str
    payload: str

# In-memory tracking for fast inspection
processed_log: List[Dict[str, Any]] = []

@app.post("/notify")
async def receive_notification(notif: NotificationRequest, response: Response):
    """
    Receives notification from transactional outbox worker.
    Guarantees idempotency via persistent processed ledger in SQLite.
    """
    # 1. Check persistent SQLite ledger
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT event_key FROM processed_notifications WHERE event_key = ?;", (notif.event_key,))
        row = cursor.fetchone()
        
        if row:
            # Duplicate notification delivery detected
            print(f"[NOTIF 9000] DUPLICATE IGNORED: {notif.event_key}")
            return {
                "status": "already_processed",
                "event_key": notif.event_key,
                "message": "Duplicate ignored via idempotent ledger"
            }
            
        # 2. Record new notification in ledger
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO processed_notifications (event_key, order_id, status, processed_at)
            VALUES (?, ?, ?, ?);
        """, (notif.event_key, notif.order_id, notif.status, now_iso))
        cursor.close()
        
    entry = {
        "event_key": notif.event_key,
        "order_id": notif.order_id,
        "status": notif.status,
        "payload": notif.payload,
        "delivered_at": now_iso
    }
    processed_log.append(entry)
    print(f"[NOTIF 9000] DELIVERED: {notif.event_key} for Order {notif.order_id}")
    
    response.status_code = status.HTTP_200_OK
    return {"status": "delivered", "event_key": notif.event_key}

@app.get("/notifications")
async def list_notifications():
    """Returns log of received notifications."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT event_key, order_id, status, processed_at FROM processed_notifications ORDER BY processed_at DESC;")
        rows = [dict(r) for r in cursor.fetchall()]
        cursor.close()
    return {
        "count": len(rows),
        "notifications": rows
    }

@app.post("/reset")
async def reset_notifications():
    """Resets notification log for testing."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM processed_notifications;")
        cursor.close()
    processed_log.clear()
    return {"status": "reset_successful"}

if __name__ == "__main__":
    uvicorn.run("app.mock_notification_service:app", host="0.0.0.0", port=9000, reload=False)

