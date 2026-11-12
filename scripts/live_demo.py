"""
CrumbTail Live Interactive System Demo
Executes a complete real-time order lifecycle journey through the running cluster:
1. Online delivery partner registration in Koramangala
2. Customer order placement (SQLite WAL commit + Redis cache mirroring)
3. Kitchen acceptance with atomic nearest-rider assignment (assign_rider.lua)
4. Monotonic 1 Hz GPS telemetry streaming
5. Transactional outbox asynchronous dispatch to Port 9000
6. Concurrency hammer test (20-order race burst -> 0 double bookings)
"""

import time
import json
import urllib.request
from typing import Dict, Any

BASE_URL = "http://127.0.0.1:8000"
NOTIF_URL = "http://127.0.0.1:9000"

def post_json(url: str, data: Dict[str, Any]) -> Dict[str, Any]:
    encoded = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))

def get_json(url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(url) as res:
        return json.loads(res.read().decode("utf-8"))

def run_demo():
    print("======================================================================")
    print("            CRUMB TAIL — LIVE INTERACTIVE SYSTEM DEMO                 ")
    print("======================================================================\n")

    # 1. Register rider nearby in Koramangala
    print("📍 [Step 1] Registering Delivery Partner in Koramangala (12.9750, 77.5900)...")
    reg_url = f"{BASE_URL}/riders/rider_vikram/register?lat=12.9750&lon=77.5900"
    req = urllib.request.Request(reg_url, method="POST")
    with urllib.request.urlopen(req) as res:
        reg_res = json.loads(res.read().decode("utf-8"))
        print(f"   Partner Online: ID={reg_res['rider_id']}, Status={reg_res['status']}, Coords=({reg_res['lat']}, {reg_res['lon']})")

    # 2. Place Customer Order
    print("\n🛒 [Step 2] Customer places order at Meghana Foods Koramangala...")
    order = post_json(f"{BASE_URL}/orders", {
        "customer_id": "cust_ananya_01",
        "restaurant_id": "rest_meghana_koramangala",
        "items": ["Special Chicken Biryani", "Paneer Tikka"]
    })
    order_id = order["id"]
    print(f"   Order Placed in SQLite: ID={order_id}, Status='{order['status']}'")

    # 3. Accept Order & Atomic Nearest Rider Assignment
    print("\n⚡ [Step 3] Kitchen accepts order -> Atomic Nearest Rider Lua Script triggers...")
    assigned = post_json(f"{BASE_URL}/orders/{order_id}/status", {
        "status": "accepted",
        "latitude": 12.9750,
        "longitude": 77.5900
    })
    rider_id = assigned.get("rider_id")
    print(f"   Order Status: '{assigned.get('status')}'")
    print(f"   Assigned Partner: '{rider_id}' (Zero race condition guaranteed)")

    # 4. Stream 5 Real-Time GPS Telemetry Pings
    print(f"\n🛵 [Step 4] Rider '{rider_id}' moves along transit path towards customer...")
    start_lat, start_lon = 12.9750, 77.5900
    end_lat, end_lon = 12.9650, 77.6050

    for seq in range(1, 6):
        progress = seq / 5.0
        lat = start_lat + (end_lat - start_lat) * progress
        lon = start_lon + (end_lon - start_lon) * progress
        ping_res = post_json(f"{BASE_URL}/locations", {
            "rider_id": rider_id,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "seq": seq,
            "device_id": f"dev_{rider_id}"
        })
        print(f"   [GPS ping seq={seq}] Lat: {lat:.4f}, Lon: {lon:.4f} -> Accepted: {ping_res.get('accepted')}")
        time.sleep(0.3)

    # 5. Outbox Notification Ledger Audit
    print("\n📬 [Step 5] Auditing Standalone Notification Service (Port 9000)...")
    time.sleep(1.0)
    notif_data = get_json(f"{NOTIF_URL}/notifications")
    print(f"   Total Notifications Processed in Ledger: {notif_data['count']}")
    recent = [n['event_key'] for n in notif_data['notifications'][:3]]
    print(f"   Most Recent Delivered Alerts: {recent}")

    # 6. Concurrency Hammer Check
    print("\n🔨 [Step 6] Running Chaos Race Hammer (20 Orders competing for 1 Rider)...")
    burst = post_json(f"{BASE_URL}/chaos/burst-orders", {
        "num_orders": 20,
        "latitude": 12.9750,
        "longitude": 77.5900
    })
    print(f"   Total Requests: {burst['total_requests']}")
    print(f"   Double Bookings: {burst['double_bookings']}")
    print(f"   Execution Latency: {burst['duration_ms']} ms")
    print(f"   Guarantee Verified: {burst['guarantee_verified']}")

    print("\n======================================================================")
    print("                 LIVE DEMO EXECUTION COMPLETE                         ")
    print("======================================================================")

if __name__ == "__main__":
    run_demo()
