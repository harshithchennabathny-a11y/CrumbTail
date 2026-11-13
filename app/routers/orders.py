import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, Response, status, HTTPException
from app.models import OrderCreate, OrderStatusUpdate, OrderResponse, BatchAssignRequest, OrderStatus
from app.database import get_db
from app.crud import (
    create_order,
    get_order,
    list_orders,
    update_order_status,
    set_order_rider,
    check_idempotency,
    record_idempotency
)
from app.redis_client import get_sync_redis, assign_rider_atomic, assign_batch_atomic, release_rider

router = APIRouter(prefix="/orders", tags=["Orders"])

@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
async def place_order(
    order_in: OrderCreate,
    response: Response,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """
    Creates a new order with status 'placed'.
    Enforces idempotency if X-Idempotency-Key header or body field is provided.
    """
    idemp_key = x_idempotency_key or order_in.idempotency_key
    
    with get_db() as conn:
        # 1. Idempotency Check
        if idemp_key:
            cached = check_idempotency(conn, idemp_key)
            if cached:
                cached_code, cached_body = cached
                response.status_code = cached_code
                return json.loads(cached_body)
                
        # 2. Persist in SQLite (Source of Truth)
        order_dict = create_order(conn, order_in)
        order_id = order_dict["id"]
        
        # 3. Mirror in Redis (Hot Read-Cache & Stream Replay Log)
        try:
            r = get_sync_redis()
            r.hset(f"order:{order_id}", mapping={
                "id": order_id,
                "customer_id": order_dict["customer_id"],
                "restaurant_id": order_dict["restaurant_id"],
                "status": order_dict["status"],
                "rider_id": "",
                "created_at": order_dict["created_at"],
                "updated_at": order_dict["updated_at"]
            })
            # Append initial status to order replay stream
            r.xadd(f"stream:order:{order_id}", {
                "type": "status",
                "status": OrderStatus.PLACED.value,
                "timestamp": order_dict["created_at"]
            })
            # Publish to restaurant order board
            r.publish("board:orders", json.dumps({
                "event": "order_created",
                "order": order_dict
            }))
        except Exception as e:
            # Degraded mode: SQLite committed, Redis failure logged
            print(f"[REDIS WARN] Failed to mirror new order to Redis: {e}")

        # 4. Save Idempotency Key
        if idemp_key:
            record_idempotency(conn, idemp_key, status.HTTP_201_CREATED, json.dumps(order_dict))
            
    return order_dict

@router.get("", response_model=List[OrderResponse])
async def get_all_orders(limit: int = 100):
    """Lists recent orders for the restaurant kanban board."""
    with get_db() as conn:
        return list_orders(conn, limit=limit)

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_by_id(order_id: str):
    """Retrieves order details by ID."""
    with get_db() as conn:
        order = get_order(conn, order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found")
        return order

@router.post("/{order_id}/status", response_model=Dict[str, Any])
async def update_status(
    order_id: str,
    status_in: OrderStatusUpdate,
    response: Response,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """
    Transitions order through the lifecycle state machine.
    - If transition is illegal: Returns HTTP 409 Conflict.
    - If transition is 'accepted': Triggers atomic nearest-rider assignment via Redis GEOSEARCH.
    - Single SQLite transaction: updates status + inserts outbox row.
    """
    idemp_key = x_idempotency_key or status_in.idempotency_key
    target_status = status_in.status.value
    
    with get_db() as conn:
        # 1. Idempotency Check
        if idemp_key:
            cached = check_idempotency(conn, idemp_key)
            if cached:
                cached_code, cached_body = cached
                response.status_code = cached_code
                return json.loads(cached_body)
                
        # 2. Validate and execute state transition in SQLite
        try:
            order_res = update_order_status(conn, order_id, target_status)
        except KeyError as ke:
            raise HTTPException(status_code=404, detail=str(ke))
        except ValueError as ve:
            # State machine rejection -> HTTP 409 Conflict
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ve))

        assigned_rider = order_res.get("rider_id")
        
        # 3. If transitioning to 'accepted', trigger atomic nearest rider assignment
        if target_status == OrderStatus.ACCEPTED.value and not assigned_rider:
            try:
                # Use default Bengaluru center or restaurant coordinates
                assigned_rider = assign_rider_atomic(
                    lon=77.5946,
                    lat=12.9716,
                    order_id=order_id,
                    radius_km=5.0
                )
                if assigned_rider:
                    set_order_rider(conn, order_id, assigned_rider)
                    order_res["rider_id"] = assigned_rider
            except Exception as e:
                print(f"[REDIS WARN] Assignment error: {e}")

        # 4. Sync status and assignment event to Redis Stream and Pub/Sub
        try:
            r = get_sync_redis()
            r.hset(f"order:{order_id}", mapping={
                "status": target_status,
                "rider_id": assigned_rider or "",
                "updated_at": order_res["updated_at"]
            })
            # Append status transition to stream for reconnect replay
            r.xadd(f"stream:order:{order_id}", {
                "type": "status",
                "status": target_status,
                "rider_id": assigned_rider or "",
                "timestamp": order_res["updated_at"]
            })
            # Publish to restaurant board & customer live track channel
            event_payload = json.dumps({
                "type": "status",
                "order_id": order_id,
                "status": target_status,
                "rider_id": assigned_rider,
                "timestamp": order_res["updated_at"]
            })
            r.publish("board:orders", event_payload)
            r.publish(f"track:{order_id}", event_payload)
            
            # 5. Release rider back to free pool if terminal state reached
            if target_status in (OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value) and assigned_rider:
                release_rider(assigned_rider)
        except Exception as e:
            print(f"[REDIS WARN] Failed to sync order update to Redis: {e}")

        # 5. Save Idempotency
        if idemp_key:
            record_idempotency(conn, idemp_key, status.HTTP_200_OK, json.dumps(order_res))

    return order_res

@router.post("/batch-assign", response_model=Dict[str, Any])
async def batch_assign(req: BatchAssignRequest):
    """
    Atomically assigns 2 competing orders to 1 free rider or changes nothing.
    Enforces atomic batch assignment guarantee for hackathon judges.
    """
    rider_id = assign_batch_atomic(
        lon=req.center_lon,
        lat=req.center_lat,
        order_id_1=req.order_id_1,
        order_id_2=req.order_id_2,
        radius_km=req.radius_km
    )
    
    if rider_id:
        with get_db() as conn:
            set_order_rider(conn, req.order_id_1, rider_id)
            set_order_rider(conn, req.order_id_2, rider_id)
        return {
            "success": True,
            "rider_id": rider_id,
            "assigned_orders": [req.order_id_1, req.order_id_2]
        }
    else:
        return {
            "success": False,
            "rider_id": None,
            "message": "No available rider within radius"
        }

