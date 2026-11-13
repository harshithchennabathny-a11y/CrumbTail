import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
import sqlite3
from app.models import OrderCreate, OrderStatus

# Strict state machine transition rules (Handbook Section 4.7)
ALLOWED_TRANSITIONS: Dict[str, List[str]] = {
    OrderStatus.PLACED.value: [OrderStatus.ACCEPTED.value, OrderStatus.CANCELLED.value],
    OrderStatus.ACCEPTED.value: [OrderStatus.PREPARING.value, OrderStatus.CANCELLED.value],
    OrderStatus.PREPARING.value: [OrderStatus.PICKED_UP.value, OrderStatus.CANCELLED.value],
    OrderStatus.PICKED_UP.value: [OrderStatus.DELIVERED.value],
    OrderStatus.DELIVERED.value: [],
    OrderStatus.CANCELLED.value: []
}

def check_idempotency(conn: sqlite3.Connection, key: str) -> Optional[Tuple[int, str]]:
    """Checks if an idempotency key was previously processed."""
    cursor = conn.cursor()
    cursor.execute("SELECT response_code, response_body FROM idempotency_keys WHERE key = ?;", (key,))
    row = cursor.fetchone()
    cursor.close()
    if row:
        return (row[0], row[1])
    return None

def record_idempotency(conn: sqlite3.Connection, key: str, code: int, body: str) -> None:
    """Stores an idempotency key and its serialized response."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO idempotency_keys (key, response_code, response_body)
        VALUES (?, ?, ?);
    """, (key, code, body))
    cursor.close()

def create_order(conn: sqlite3.Connection, order_in: OrderCreate, order_id: Optional[str] = None) -> Dict[str, Any]:
    """Inserts a new order into SQLite in 'placed' state and records creation event."""
    oid = order_id or f"ord_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (id, customer_id, restaurant_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (oid, order_in.customer_id, order_in.restaurant_id, OrderStatus.PLACED.value, now_iso, now_iso))
    
    cursor.execute("""
        INSERT INTO order_events (order_id, from_status, to_status)
        VALUES (?, NULL, ?);
    """, (oid, OrderStatus.PLACED.value))
    
    cursor.close()
    return {
        "id": oid,
        "customer_id": order_in.customer_id,
        "restaurant_id": order_in.restaurant_id,
        "rider_id": None,
        "status": OrderStatus.PLACED.value,
        "created_at": now_iso,
        "updated_at": now_iso
    }

def get_order(conn: sqlite3.Connection, order_id: str) -> Optional[Dict[str, Any]]:
    """Fetches order record by ID."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, customer_id, restaurant_id, rider_id, status, created_at, updated_at
        FROM orders WHERE id = ?;
    """, (order_id,))
    row = cursor.fetchone()
    cursor.close()
    if not row:
        return None
    return dict(row)

def list_orders(conn: sqlite3.Connection, limit: int = 100) -> List[Dict[str, Any]]:
    """Lists orders ordered by recency."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, customer_id, restaurant_id, rider_id, status, created_at, updated_at
        FROM orders ORDER BY created_at DESC LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    cursor.close()
    return [dict(r) for r in rows]

def update_order_status(
    conn: sqlite3.Connection,
    order_id: str,
    new_status: str,
    rider_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enforces the order lifecycle state machine.
    In one single SQLite transaction:
    1. Validates legal transition (or raises ValueError -> HTTP 409).
    2. Updates order status in 'orders'.
    3. Inserts transactional outbox row ('orderId:status').
    4. Inserts audit record in 'order_events'.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT status, rider_id FROM orders WHERE id = ?;", (order_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        raise KeyError(f"Order '{order_id}' not found")
        
    current_status = row[0]
    existing_rider = row[1]
    
    # 1. State machine validation
    allowed = ALLOWED_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        cursor.close()
        raise ValueError(f"Invalid state transition: cannot transition from '{current_status}' to '{new_status}'")
    
    now_iso = datetime.now(timezone.utc).isoformat()
    assigned_rider = rider_id if rider_id is not None else existing_rider
    
    # 2. Update order record
    cursor.execute("""
        UPDATE orders
        SET status = ?, rider_id = ?, updated_at = ?
        WHERE id = ?;
    """, (new_status, assigned_rider, now_iso, order_id))
    
    # 3. Insert into transactional outbox
    event_key = f"{order_id}:{new_status}"
    payload = json.dumps({
        "order_id": order_id,
        "status": new_status,
        "rider_id": assigned_rider,
        "timestamp": now_iso
    })
    
    cursor.execute("""
        INSERT OR IGNORE INTO outbox (event_key, order_id, status, payload, state)
        VALUES (?, ?, ?, ?, 'pending');
    """, (event_key, order_id, new_status, payload))
    
    # 4. Record audit history
    cursor.execute("""
        INSERT INTO order_events (order_id, from_status, to_status)
        VALUES (?, ?, ?);
    """, (order_id, current_status, new_status))
    
    cursor.close()
    return {
        "id": order_id,
        "status": new_status,
        "rider_id": assigned_rider,
        "updated_at": now_iso
    }

def set_order_rider(conn: sqlite3.Connection, order_id: str, rider_id: str) -> None:
    """Updates assigned rider for an order."""
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET rider_id = ? WHERE id = ?;", (rider_id, order_id))
    cursor.close()

def get_pending_outbox_rows(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves pending outbox rows ready for dispatch."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, event_key, order_id, status, payload, retry_count
        FROM outbox
        WHERE state = 'pending' AND datetime(next_retry_at) <= datetime('now')
        ORDER BY id ASC LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    cursor.close()
    return [dict(r) for r in rows]

def claim_outbox_batch(conn: sqlite3.Connection, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Atomically claims a batch of pending outbox rows by transitioning state to 'processing'.
    Prevents race conditions when multiple outbox workers run concurrently.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, event_key, order_id, status, payload, retry_count
        FROM outbox
        WHERE state = 'pending' AND datetime(next_retry_at) <= datetime('now')
        ORDER BY id ASC LIMIT ?;
    """, (limit,))
    rows = cursor.fetchall()
    if rows:
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        cursor.execute(f"UPDATE outbox SET state = 'processing' WHERE id IN ({placeholders});", ids)
    cursor.close()
    return [dict(r) for r in rows]

def mark_outbox_sent(conn: sqlite3.Connection, outbox_id: int) -> None:
    """Marks outbox row as sent."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE outbox SET state = 'sent', sent_at = ? WHERE id = ?;
    """, (now_iso, outbox_id))
    cursor.close()

def mark_outbox_failed_retry(conn: sqlite3.Connection, outbox_id: int, current_retries: int, delay_seconds: float) -> None:
    """Updates outbox row for retry with exponential backoff and randomized jitter."""
    next_time = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE outbox
        SET retry_count = ?, next_retry_at = ?, state = 'pending'
        WHERE id = ?;
    """, (current_retries + 1, next_time, outbox_id))
    cursor.close()

