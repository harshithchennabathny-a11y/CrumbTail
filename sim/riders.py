"""
CrumbTail Rider Simulator — Bangalore, 50 riders, A* routing.
State machine: idle -> to_pickup -> waiting_at_restaurant -> to_dropoff -> delivered -> idle

Usage: python sim/riders.py --riders 50 --speed 5 --url http://localhost:8000
"""
import asyncio, time, math, random, argparse, json, sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    print("httpx not installed. Run: pip install httpx")
    sys.exit(1)

BANGALORE_BOUNDS = {
    "min_lat": 12.84, "max_lat": 13.05,
    "min_lon": 77.55, "max_lon": 77.75
}
# Speed in m/s for road travel (20 km/h = 5.56 m/s, multiplied by sim_speed)
BASE_SPEED_MS = 5.56  # 20 km/h

def haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def straight_polyline(lat1, lon1, lat2, lon2, steps=12) -> List[Tuple[float, float]]:
    """Fallback straight-line path with realistic jitter."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        lat = lat1 + (lat2 - lat1) * t + random.uniform(-0.0003, 0.0003)
        lon = lon1 + (lon2 - lon1) * t + random.uniform(-0.0003, 0.0003)
        pts.append((lat, lon))
    # Ensure exact endpoints
    pts[0] = (lat1, lon1)
    pts[-1] = (lat2, lon2)
    return pts

@dataclass
class SimRider:
    rider_id: str
    lat: float
    lon: float
    sim_speed: float = 5.0
    
    # State machine
    state: str = "idle"           # idle | to_pickup | waiting_at_restaurant | to_dropoff | delivered
    active_order_id: str = ""
    pickup_lat: float = 0.0
    pickup_lon: float = 0.0
    dropoff_lat: float = 0.0
    dropoff_lon: float = 0.0
    restaurant_id: str = ""
    
    # Path following
    path: List[Tuple[float, float]] = field(default_factory=list)
    path_idx: int = 0
    
    # Monotonic seq (epoch-ms base, never resets)
    seq: int = field(default_factory=lambda: int(time.time() * 1000) + random.randint(0, 999))
    
    # Idle drift
    idle_heading: float = field(default_factory=lambda: random.uniform(0, 360))
    
    def next_seq(self) -> int:
        self.seq += random.randint(1, 3)
        return self.seq
    
    def step_along_path(self, dt_sec: float) -> bool:
        """Move along current path. Returns True when path is complete."""
        if not self.path or self.path_idx >= len(self.path) - 1:
            return True
        
        # How far can we travel in dt_sec?
        dist_budget = BASE_SPEED_MS * self.sim_speed * dt_sec
        
        while dist_budget > 0 and self.path_idx < len(self.path) - 1:
            nx, ny = self.path[self.path_idx + 1]
            seg_dist = haversine_m(self.lat, self.lon, nx, ny)
            if seg_dist <= dist_budget:
                self.lat, self.lon = nx, ny
                self.path_idx += 1
                dist_budget -= seg_dist
            else:
                # Partial advance along segment
                frac = dist_budget / seg_dist if seg_dist > 0 else 0
                self.lat += (nx - self.lat) * frac
                self.lon += (ny - self.lon) * frac
                dist_budget = 0
        
        return self.path_idx >= len(self.path) - 1
    
    def idle_drift(self, dt_sec: float):
        """Small random walk while idle, keeps heartbeat fresh."""
        self.idle_heading += random.uniform(-20, 20)
        rad = math.radians(self.idle_heading)
        speed = BASE_SPEED_MS * 0.3 * dt_sec  # slow drift
        # Convert m to degrees (approx)
        dlat = (speed * math.cos(rad)) / 111_320
        dlon = (speed * math.sin(rad)) / (111_320 * math.cos(math.radians(self.lat)))
        self.lat = max(BANGALORE_BOUNDS["min_lat"], min(BANGALORE_BOUNDS["max_lat"], self.lat + dlat))
        self.lon = max(BANGALORE_BOUNDS["min_lon"], min(BANGALORE_BOUNDS["max_lon"], self.lon + dlon))


class RiderSimulator:
    def __init__(self, num_riders: int = 50, sim_speed: float = 5.0,
                 base_url: str = "http://localhost:8000", tick_hz: float = 1.0):
        self.num_riders = num_riders
        self.sim_speed = sim_speed
        self.base_url = base_url
        self.tick_hz = tick_hz
        self.tick_interval = 1.0 / tick_hz
        self.riders: Dict[str, SimRider] = {}
        self.client: Optional[httpx.AsyncClient] = None
        self._running = False
    
    async def initialize(self):
        """Register all riders and load their initial positions."""
        limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
        self.client = httpx.AsyncClient(
            base_url=self.base_url, timeout=5.0, limits=limits
        )
        
        HUBS = [
            (12.9784, 77.6408), (12.9352, 77.6245), (12.9116, 77.6389),
            (12.9166, 77.6101), (12.9308, 77.5838), (12.9063, 77.5857),
            (12.9757, 77.6068), (13.0035, 77.5710), (12.9569, 77.7011),
            (12.9698, 77.7500), (13.0358, 77.5970), (12.8452, 77.6602),
            (12.9308, 77.5726), (12.9716, 77.5946), (12.9500, 77.6300),
        ]
        
        for i in range(1, self.num_riders + 1):
            rid = f"rider_{i:04d}"
            hub = HUBS[i % len(HUBS)]
            lat = hub[0] + random.uniform(-0.015, 0.015)
            lon = hub[1] + random.uniform(-0.015, 0.015)
            rider = SimRider(rider_id=rid, lat=lat, lon=lon, sim_speed=self.sim_speed)
            self.riders[rid] = rider
            # Register via API
            try:
                await self.client.post(f"/riders/{rid}/register", params={"lat": lat, "lon": lon})
            except Exception:
                pass
        
        print(f"[SIM] Initialized {len(self.riders)} riders")
    
    async def _get_route(self, lat1, lon1, lat2, lon2) -> List[Tuple[float, float]]:
        """Fetch A* route from backend."""
        try:
            resp = await self.client.get("/demo/route", params={
                "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2
            }, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return [(p["lat"], p["lon"]) for p in data["polyline"]]
        except Exception:
            pass
        return straight_polyline(lat1, lon1, lat2, lon2)
    
    async def _send_location(self, rider: SimRider):
        """POST location to backend."""
        try:
            payload = {
                "rider_id": rider.rider_id,
                "lat": round(rider.lat, 7),
                "lon": round(rider.lon, 7),
                "seq": rider.next_seq(),
                "device_id": f"dev_{rider.rider_id}",
                "timestamp": int(time.time()),
                "state": rider.state
            }
            await self.client.post("/locations", json=payload, timeout=3.0)
        except Exception:
            pass
    
    async def _check_for_assignment(self, rider: SimRider):
        """Poll rider state to see if an order was assigned."""
        try:
            resp = await self.client.get(f"/riders/{rider.rider_id}/state", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                order_id = data.get("active_order_id", "")
                if order_id and rider.state == "idle":
                    # Got a new order assignment!
                    order_resp = await self.client.get(f"/orders/{order_id}", timeout=3.0)
                    if order_resp.status_code == 200:
                        order = order_resp.json()
                        rest_id = order.get("restaurant_id", "")
                        # Get restaurant location
                        rest_resp = await self.client.get(f"/demo/restaurants", timeout=3.0)
                        rest_lat, rest_lon = 12.9716, 77.5946
                        if rest_resp.status_code == 200:
                            rests = rest_resp.json().get("restaurants", [])
                            for r in rests:
                                if r["id"] == rest_id:
                                    rest_lat, rest_lon = r["lat"], r["lon"]
                                    break
                        
                        dlat = float(order.get("delivery_lat") or 12.9716)
                        dlon = float(order.get("delivery_lon") or 77.5946)
                        
                        rider.active_order_id = order_id
                        rider.pickup_lat = rest_lat
                        rider.pickup_lon = rest_lon
                        rider.dropoff_lat = dlat
                        rider.dropoff_lon = dlon
                        rider.restaurant_id = rest_id
                        
                        # Plan path to pickup
                        rider.path = await self._get_route(rider.lat, rider.lon, rest_lat, rest_lon)
                        rider.path_idx = 0
                        rider.state = "to_pickup"
                        print(f"[SIM] {rider.rider_id} → to_pickup for order {order_id}")
        except Exception:
            pass
    
    async def _advance_order_status(self, rider: SimRider, new_status: str):
        """Advance order status via REST API."""
        try:
            await self.client.post(
                f"/orders/{rider.active_order_id}/status",
                json={"status": new_status}, timeout=5.0
            )
        except Exception:
            pass
    
    async def _tick_rider(self, rider: SimRider, dt: float):
        """One simulation tick for one rider."""
        if rider.state == "idle":
            rider.idle_drift(dt)
            await self._send_location(rider)
            # Check if assigned
            if random.random() < 0.3:  # check 30% of ticks to reduce load
                await self._check_for_assignment(rider)
        
        elif rider.state == "to_pickup":
            done = rider.step_along_path(dt)
            await self._send_location(rider)
            if done:
                rider.state = "waiting_at_restaurant"
                print(f"[SIM] {rider.rider_id} arrived at pickup for {rider.active_order_id}")
                await self._advance_order_status(rider, "preparing")
                await asyncio.sleep(random.uniform(2.0, 6.0) / rider.sim_speed)
                await self._advance_order_status(rider, "picked_up")
                # Plan route to dropoff
                rider.path = await self._get_route(
                    rider.pickup_lat, rider.pickup_lon,
                    rider.dropoff_lat, rider.dropoff_lon
                )
                rider.path_idx = 0
                rider.lat, rider.lon = rider.pickup_lat, rider.pickup_lon
                rider.state = "to_dropoff"
                print(f"[SIM] {rider.rider_id} → to_dropoff")
        
        elif rider.state == "waiting_at_restaurant":
            await self._send_location(rider)  # Stay at pickup location
        
        elif rider.state == "to_dropoff":
            done = rider.step_along_path(dt)
            await self._send_location(rider)
            if done:
                rider.state = "delivered"
                print(f"[SIM] {rider.rider_id} delivered {rider.active_order_id}")
                await self._advance_order_status(rider, "delivered")
                rider.active_order_id = ""
                rider.state = "idle"
        
        elif rider.state == "delivered":
            # Transition back handled above
            rider.state = "idle"
    
    async def run(self):
        """Main simulation loop."""
        self._running = True
        await self.initialize()
        
        print(f"[SIM] Starting main loop — {self.num_riders} riders @ {self.sim_speed}x speed, {self.tick_hz} Hz")
        last_tick = time.time()
        tick_count = 0
        
        while self._running:
            now = time.time()
            dt = now - last_tick
            last_tick = now
            tick_count += 1
            
            # Tick all riders concurrently (batched for efficiency)
            tasks = [self._tick_rider(r, dt) for r in self.riders.values()]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            if tick_count % 10 == 0:
                busy = sum(1 for r in self.riders.values() if r.state != "idle")
                print(f"[SIM] Tick {tick_count} | Busy riders: {busy}/{self.num_riders}")
            
            # Sleep until next tick
            elapsed = time.time() - last_tick
            await asyncio.sleep(max(0.0, self.tick_interval - elapsed))
        
        await self.client.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--riders", type=int, default=50)
    parser.add_argument("--speed", type=float, default=5.0, help="Simulation speed multiplier")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--hz", type=float, default=1.0, help="Location update frequency")
    args = parser.parse_args()
    
    sim = RiderSimulator(
        num_riders=args.riders,
        sim_speed=args.speed,
        base_url=args.url,
        tick_hz=args.hz
    )
    asyncio.run(sim.run())

if __name__ == "__main__":
    main()
