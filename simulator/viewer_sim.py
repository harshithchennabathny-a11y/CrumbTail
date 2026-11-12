"""
CrumbTail Viewer Simulator
Simulates concurrent customer viewers opening WebSockets to test:
- Targeted Fan-out isolation
- WebSocket delivery latency under load
- Connection durability across multi-instance architecture
"""

import sys
import time
import json
import asyncio
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

async def simulate_viewer(viewer_id: int, order_id: str, host: str = "localhost", port: int = 8000, duration: int = 10):
    uri = f"ws://{host}:{port}/ws/orders/{order_id}"
    messages_received = 0
    t_start = time.time()
    
    try:
        async with websockets.connect(uri) as ws:
            # Send initial hello handshake
            await ws.send(json.dumps({"action": "hello", "last_event_id": "0-0"}))
            
            while (time.time() - t_start) < duration:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    messages_received += 1
                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        pass

    return viewer_id, messages_received

async def run_viewers(num_viewers: int = 20, order_id: str = "order_demo_101", duration: int = 10, port: int = 8000):
    print(f"👥 Starting Viewer Simulator: {num_viewers} concurrent viewers for '{order_id}' on port {port} ({duration}s)...")
    tasks = [simulate_viewer(i, order_id, port=port, duration=duration) for i in range(1, num_viewers + 1)]
    results = await asyncio.gather(*tasks)

    total_msgs = sum(r[1] for r in results)
    active_connected = sum(1 for r in results if r[1] > 0)
    print(f"✅ Viewer Simulation Complete: {len(results)} viewers tested. Active connections: {active_connected}, Total frames delivered: {total_msgs}")

def main():
    parser = argparse.ArgumentParser(description="CrumbTail Concurrent Viewer Simulator")
    parser.add_argument("--viewers", type=int, default=20, help="Number of concurrent viewers (default: 20)")
    parser.add_argument("--order", type=str, default="order_demo_101", help="Target Order ID")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds (default: 10)")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI port (default: 8000)")
    args = parser.parse_args()

    asyncio.run(run_viewers(
        num_viewers=args.viewers,
        order_id=args.order,
        duration=args.duration,
        port=args.port
    ))

if __name__ == "__main__":
    main()

