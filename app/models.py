from enum import Enum
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field

class OrderStatus(str, Enum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class OrderCreate(BaseModel):
    customer_id: str = Field(..., description="Unique customer identifier")
    restaurant_id: str = Field(..., description="Unique restaurant identifier")
    items: List[Any] = Field(default_factory=list, description="Order item objects or names")
    delivery_lat: Optional[float] = Field(default=12.9716, description="Destination latitude")
    delivery_lon: Optional[float] = Field(default=77.5946, description="Destination longitude")
    idempotency_key: Optional[str] = Field(default=None, description="Optional client idempotency key")

class OrderStatusUpdate(BaseModel):
    status: OrderStatus = Field(..., description="Target lifecycle state")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key")

class OrderResponse(BaseModel):
    id: str
    customer_id: str
    restaurant_id: str
    rider_id: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class NotificationMessage(BaseModel):
    event_key: str
    order_id: str
    status: str
    payload: str
    timestamp: Optional[str] = None

class BatchAssignRequest(BaseModel):
    order_id_1: str
    order_id_2: str
    center_lat: float = 12.9716
    center_lon: float = 77.5946
    radius_km: float = 5.0

class LocationIngest(BaseModel):
    rider_id: str = Field(..., description="Unique rider identifier")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    seq: int = Field(..., description="Monotonically increasing sequence number")
    timestamp: Optional[int] = Field(default=None, description="Unix timestamp (seconds)")
    device_id: Optional[str] = Field(default=None, description="Device identifier for rate limiting")

