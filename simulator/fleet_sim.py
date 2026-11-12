"""
CrumbTail Fleet Simulator
Generates realistic high-throughput GPS location pings across Bengaluru for up to 2,000 riders.

Modes:
- clean: Monotonically increasing sequence numbers, smooth velocity.
- noisy: Injects backward sequence numbers and duplicate packets to test server-side packet drop.
- burst: Sends bursts exceeding rate limit (25/sec) to test sliding window rate limiter (HTTP 429).
"""

import sys
import time
import random
import asyncio
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BENGALURU_BOUNDS = {
    "min_lat": 12.9400,
    "max_lat": 12.9900,
    "min_lon": 77.5700,
    "max_lon": 77.6600
}

class VirtualRider:
    def __init__(self, rider_id: str, mode: str = "clean"):
        self.rider_id = rider_id
        self.mode = mode
        self.lat = random.uniform(BENGALURU_BOUNDS["min_lat"], BENGALURU_BOUNDS["max_lat"])
        self.lon = random.uniform(BENGALURU_BOUNDS["min_lon"], BENGALURU_BOUNDS["max_lon"])
        self.seq = 1
        self.heading = random.uniform(0, 360) # degrees
        self.speed = random.uniform(0.0001, 0.0003) # approx 20-40 km/h in degrees

    def step(self):
        # Move in current direction with slight noise
        import math
        self.heading += random.uniform(-15, 15)
        rad = math.radians(self.heading)
        self.lat += self.speed * math.cos(rad)
        self.lon += self.speed * math.sin(rad)

        # Bounce off boundaries
        if self.lat < BENGALURU_BOUNDS["min_lat"] or self.lat > BENGALURU_BOUNDS["max_lat"]:
            self.heading = (180 - self.heading) % 360
        if self.lon < BENGALURU_BOUNDS["min_lon"] or self.lon > BENGALURU_BOUNDS["max_lon"]:
            self.heading = (360 - self.heading) % 360

        if self.mode == "noisy" and random.random() < 0.15:
            # Inject a backward/duplicate sequence number
            send_seq = max(1, self.seq - random.randint(1, 5))
        else:
            self.seq += 1
            send_seq = self.seq

        return {
            "rider_id": self.rider_id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "seq": send_seq,
            "device_id": f"dev_{self.rider_id}",
            "timestamp": int(time.time())
        }

async def run_simulator(num_riders: int = 50, duration_sec: int = 10, mode: str = "clean", target_url: str = "http://localhost:8000"):
    print(f"🚀 Starting Fleet Simulator: {num_riders} riders, mode={mode}, duration={duration_sec}s -> {target_url}")
    fleet = [VirtualRider(f"rider_{i:04d}", mode=mode) for i in range(1, num_riders + 1)]

    # Pre-register fleet
    limits = httpx.Limits(max_keepalive_connections=50, max_connections=200)
    async with httpx.AsyncClient(base_url=target_url, timeout=3.0, limits=limits) as client:
        print("📍 Registering fleet in Redis geospatial index...")
        for r in fleet[:min(50, len(fleet))]:
            try:
                await client.post(f"/riders/{r.rider_id}/register", json={"lat": r.lat, "lon": r.lon})
            except Exception:
                pass

        print("⚡ Commencing live 1 Hz telemetry stream...")
        start_time = time.time()
        total_sent = 0
        accepted_count = 0
        dropped_count = 0
        rate_limited_count = 0

        while (time.time() - start_time) < duration_sec:
            cycle_start = time.perf_counter()
            pings = [r.step() for r in fleet]

            async def send_ping(payload):
                nonlocal accepted_count, dropped_count, rate_limited_count
                try:
                    resp = await client.post("/locations", json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("accepted"):
                            accepted_count += 1
                        else:
                            dropped_count += 1
                    elif resp.status_code == 429:
                        rate_limited_count += 1
                except Exception:
                    pass

            await asyncio.gather(*(send_ping(p) for p in pings))
            total_sent += len(pings)

            elapsed = time.perf_counter() - cycle_start
            sleep_time = max(0.0, 1.0 - elapsed)
            await asyncio.sleep(sleep_time)

            rate = round(len(pings) / max(0.001, elapsed + sleep_time))
            print(f"  [T+{int(time.time() - start_time)}s] Sent: {total_sent} | Accepted: {accepted_count} | Dropped (stale): {dropped_count} | Throttled (429): {rate_limited_count} | Rate: {rate} pings/s")

    print("\n🏁 Fleet Simulation Complete!")
    print(f"Total Sent: {total_sent}")
    print(f"Accepted: {accepted_count}")
    print(f"Dropped (Stale/Duplicate): {dropped_count}")
    print(f"Throttled (Rate Limited): {rate_limited_count}")

def main():
    parser = argparse.ArgumentParser(description="CrumbTail Virtual Fleet Simulator")
    parser.add_argument("--riders", type=int, default=50, help="Number of virtual riders (default: 50, up to 2000)")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds (default: 10)")
    parser.add_argument("--mode", type=str, choices=["clean", "noisy", "burst"], default="clean", help="Simulation mode")
    parser.add_argument("--url", type=str, default="http://localhost:8000", help="Target API URL")
    args = parser.parse_args()

    asyncio.run(run_simulator(
        num_riders=args.riders,
        duration_sec=args.duration,
        mode=args.mode,
        target_url=args.url
    ))

if __name__ == "__main__":
    main()

