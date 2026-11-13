"""
CrumbTail Restaurant Simulator — auto-advances placed→accepted and triggers dispatcher.
Runs alongside rider simulator.
"""
import asyncio, time, random, sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    print("httpx required. pip install httpx")
    sys.exit(1)

class RestaurantSim:
    def __init__(self, base_url="http://localhost:8000", interval=3.0):
        self.base_url = base_url
        self.interval = interval
        self.client = None
        self._running = False
    
    async def run(self):
        self._running = True
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=5.0)
        print(f"[REST-SIM] Starting restaurant simulator → {self.base_url}")
        
        tick = 0
        while self._running:
            tick += 1
            try:
                # 1. Fetch placed orders and auto-accept them
                resp = await self.client.get("/orders", params={"limit": 50})
                if resp.status_code == 200:
                    orders = resp.json()
                    for order in orders:
                        if order["status"] == "placed":
                            # Auto-accept after 2-6s delay (simulated by random skip)
                            if random.random() < 0.4:  # 40% chance per tick = ~avg 7.5s at 3s interval
                                await self.client.post(
                                    f"/orders/{order['id']}/status",
                                    json={"status": "accepted"}
                                )
                
                # 2. Run dispatcher every other tick to assign riders to pending queue
                if tick % 2 == 0:
                    await self.client.post("/demo/dispatcher", params={"batch": 15})
                
            except Exception as e:
                print(f"[REST-SIM] Error: {e}")
            
            await asyncio.sleep(self.interval)
        
        await self.client.aclose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()
    
    sim = RestaurantSim(base_url=args.url, interval=args.interval)
    asyncio.run(sim.run())

if __name__ == "__main__":
    main()
