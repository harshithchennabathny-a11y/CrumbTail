"""
CrumbTail Demo Scenario Runner
Usage: python sim/demo.py --orders 120 --riders 50 --speed 5

Resets the demo, seeds Bangalore data, places orders concurrently, then exits
(simulators are assumed to already be running or started by run_demo.py).
"""
import asyncio, argparse, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    print("httpx required. pip install httpx")
    sys.exit(1)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=120)
    parser.add_argument("--riders", type=int, default=50)
    parser.add_argument("--speed", type=float, default=5.0)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    
    async with httpx.AsyncClient(base_url=args.url, timeout=30.0) as client:
        print(f"[DEMO] Resetting demo state ({args.riders} riders)...")
        resp = await client.post("/demo/reset", params={"riders": args.riders})
        print(f"[DEMO] Reset: {resp.json()}")
        
        print(f"[DEMO] Placing {args.orders} orders concurrently...")
        resp = await client.post("/demo/place-orders", params={"count": args.orders})
        result = resp.json()
        print(f"[DEMO] Placed: {result['placed']} orders")
        sample_ids = result.get('order_ids') or result.get('sample_order_ids') or []
        print(f"[DEMO] Sample IDs: {sample_ids[:5]}")
        
        print(f"[DEMO] Running initial dispatcher pass...")
        resp = await client.post("/demo/dispatcher", params={"batch": args.riders})
        result = resp.json()
        waiting = result.get('no_rider', result.get('waiting', 0))
        print(f"[DEMO] Dispatcher: assigned={result.get('assigned')}, waiting={waiting}")
        
        print(f"""
[DEMO] Scenario ready!
  → {args.orders} orders placed
  → {result.get('assigned')} riders immediately assigned
  → {waiting} orders waiting for rider in Redis pending queue
  
Open in browser:
  Customer tracking: http://localhost:8000/static/index.html
  Restaurant board:  http://localhost:8000/static/restaurant.html
  Operations map:    http://localhost:8000/static/ops.html
  Demo control:      http://localhost:8000/static/demo.html
""")

if __name__ == "__main__":
    asyncio.run(main())
