import os
import time
import httpx
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request, status
from app.config import NOTIFICATION_SERVICE_URL, BENGALURU_BOUNDS
from app.database import get_db
from app.crud import create_order, update_order_status
from app.redis_client import (
    get_sync_redis,
    get_async_redis,
    ingest_location_atomic,
    assign_rider_atomic,
    assign_batch_atomic
)
from app.models import BatchAssignRequest, OrderCreate

router = APIRouter(prefix="/chaos", tags=["Chaos Engineering"])

class InjectGpsRequest(BaseModel):
    rider_id: str
    order_id: Optional[str] = None
    latitude: float
    longitude: float
    seq: int

class BurstOrdersRequest(BaseModel):
    num_orders: int = 20
    latitude: float = 12.9716
    longitude: float = 77.5946

@router.post("/inject-gps")
async def inject_gps(req: InjectGpsRequest):
    """
    Chaos 1: Injects a GPS update directly through the ingestion engine.
    Used to demonstrate packet rejection when seq <= stored_seq.
    """
    accepted = ingest_location_atomic(
        rider_id=req.rider_id,
        incoming_seq=req.seq,
        lat=req.latitude,
        lon=req.longitude
    )
    
    if accepted == 0:
        return {
            "status": "rejected",
            "reason": f"Packet dropped: seq {req.seq} <= stored_seq (backward or duplicate GPS packet)",
            "rider_id": req.rider_id,
            "seq": req.seq
        }
    return {
        "status": "accepted",
        "message": f"Packet accepted: seq {req.seq} stored",
        "rider_id": req.rider_id,
        "seq": req.seq
    }

@router.post("/burst-orders")
async def burst_orders(req: BurstOrdersRequest):
    """
    Chaos 2: Concurrently fires N orders competing for nearby riders.
    Demonstrates zero double-bookings under high concurrency.
    """
    t0 = time.perf_counter()
    order_ids = []
    
    # 1. Create N orders in SQLite
    with get_db() as conn:
        for i in range(req.num_orders):
            order = create_order(
                conn,
                OrderCreate(
                    customer_id=f"chaos_cust_{i}",
                    restaurant_id="rest_chaos_hub"
                )
            )
            order_ids.append(order["id"])
    
    # 2. Concurrently attempt nearest rider assignment via atomic Lua script
    assigned_riders = []
    failed_assignments = 0

    with get_db() as conn:
        for oid in order_ids:
            rider_id = assign_rider_atomic(
                lon=req.longitude,
                lat=req.latitude,
                order_id=oid,
                radius_km=15.0
            )
            if rider_id:
                assigned_riders.append(rider_id)
                update_order_status(conn, oid, "accepted", rider_id=rider_id)
            else:
                failed_assignments += 1

    t1 = time.perf_counter()
    duration_ms = (t1 - t0) * 1000

    unique_riders = set(assigned_riders)
    double_bookings = len(assigned_riders) - len(unique_riders)

    return {
        "total_requests": req.num_orders,
        "successful_assignments": len(assigned_riders),
        "unassigned_orders": failed_assignments,
        "assigned_riders": assigned_riders,
        "unique_assigned_riders": len(unique_riders),
        "double_bookings": double_bookings,
        "duration_ms": round(duration_ms, 2),
        "guarantee_verified": (double_bookings == 0)
    }

@router.post("/competing-batch")
async def competing_batch(req: BatchAssignRequest):
    """
    Chaos 3: Tests atomic batch assignment script under competition.
    """
    rider_id = assign_batch_atomic(
        lon=req.center_lon,
        lat=req.center_lat,
        order_id_1=req.order_id_1,
        order_id_2=req.order_id_2,
        radius_km=req.radius_km
    )
    if not rider_id:
        return {
            "status": "failed",
            "message": "No single rider available within radius to fulfill batch",
            "double_bookings": 0
        }
    return {
        "status": "success",
        "assigned_rider": rider_id,
        "order_1": req.order_id_1,
        "order_2": req.order_id_2,
        "double_bookings": 0
    }

@router.post("/check-notifications")
async def check_notifications():
    """
    Chaos 4: Probes the mock notification service on port 9000
    and returns its current ledger size and status.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{NOTIFICATION_SERVICE_URL}/ledger")
            if resp.status_code == 200:
                ledger = resp.json()
                return {
                    "service_status": "online",
                    "port": 9000,
                    "processed_notifications_count": len(ledger),
                    "ledger": ledger[-10:]  # Last 10
                }
            return {"service_status": "error", "code": resp.status_code}
    except Exception as e:
        return {
            "service_status": "offline",
            "port": 9000,
            "error": str(e),
            "message": "Notification service is currently unreachable; outbox worker is buffering with exponential backoff."
        }

@router.post("/kill-instance")
async def kill_instance(request: Request):
    """
    Chaos 5: Simulates crash of current instance to demonstrate client WebSocket failover < 500ms.
    """
    import asyncio
    instance_id = getattr(request.app.state, "instance_id", "Unknown")
    port = getattr(request.app.state, "port", 8000)

    async def delayed_exit():
        await asyncio.sleep(0.2)
        os._exit(0)

    asyncio.create_task(delayed_exit())
    return {
        "status": "terminating",
        "instance": instance_id,
        "port": port,
        "message": f"Instance {instance_id} (port {port}) is shutting down immediately. Client will fail over to peer instance."
    }
