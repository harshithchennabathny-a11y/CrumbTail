import sqlite3
from contextlib import contextmanager
from typing import Generator
from app.config import DB_PATH

def get_connection() -> sqlite3.Connection:
    """
    Returns an SQLite connection configured with WAL mode and busy timeout
    to allow concurrent multi-process writes without locking errors.
    """
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()
    return conn

@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for obtaining a database connection with auto-commit/rollback."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db() -> None:
    """Initializes all SQLite schemas required for Crumb Trail."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. Orders Table (Source of truth for order lifecycle)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            restaurant_id TEXT NOT NULL,
            rider_id TEXT,
            status TEXT NOT NULL CHECK(status IN ('placed', 'accepted', 'preparing', 'picked_up', 'delivered', 'cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 2. Transactional Outbox (Guarantees at-least-once notification dispatch)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT UNIQUE NOT NULL, -- Format: {orderId}:{status}
            order_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'processing', 'sent', 'failed')),
            retry_count INTEGER DEFAULT 0,
            next_retry_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        );
        """)

        # 3. Processed Notifications Ledger (Idempotent consumer deduplication)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_notifications (
            event_key TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            status TEXT NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 4. Order Lifecycle Audit History
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 5. Sampled Batched Location History (< 50 writes/s under 2,000 riders)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS location_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rider_id TEXT NOT NULL,
            order_id TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            seq INTEGER NOT NULL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # 6. Idempotency Keys (Deduplicates mutating requests)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key TEXT PRIMARY KEY,
            response_code INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        cursor.close()

def check_db() -> bool:
    """Verifies that SQLite is healthy and reachable."""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            res = cursor.fetchone()
            return res is not None and res[0] == 1
    except Exception:
        return False

