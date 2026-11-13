"""
A* routing for CrumbTail — road-network pathfinding over Bangalore.
Falls back to a generated grid graph if OSMnx/OSM data is not available.
Route cache keyed by (node_a, node_b) to avoid repeated computation.
All heavy computation runs in a thread pool to avoid blocking the event loop.
Uses scipy KDTree for spatial snapping if available.
"""
import heapq
import math
import time
import pickle
import random
import asyncio
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from concurrent.futures import ThreadPoolExecutor

try:
    from scipy.spatial import KDTree
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
GRAPH_CACHE = DATA_DIR / "blr_graph.pkl"

# Bangalore (Bengaluru) bounding box
MIN_LAT, MAX_LAT = 12.84, 13.05
MIN_LON, MAX_LON = 77.55, 77.75

# Grid resolution for fallback graph
GRID_ROWS, GRID_COLS = 50, 50

# Average speed for ETA computation: 25 km/h ≈ 6.94 m/s
AVG_RIDER_SPEED_MS = 6.94

_graph = None  # {node_id: {"lat": float, "lon": float, "neighbors": [(node_id, dist_m)]}}
_node_ids = []  # list of node_ids in order
_kdtree = None
_route_cache: Dict[Tuple, List[Tuple[float, float]]] = {}
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="astar")

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two lat/lon coordinates."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))

def _build_grid_graph():
    """Build a connected grid graph over Bangalore bounding box as fallback."""
    lat_step = (MAX_LAT - MIN_LAT) / GRID_ROWS
    lon_step = (MAX_LON - MIN_LON) / GRID_COLS
    graph = {}
    
    # Deterministic pseudo-random seed so all instances agree on graph structure
    rnd = random.Random(42)
    blocked = set()
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if rnd.random() < 0.15:  # 15% blocked cells to simulate non-drivable areas
                blocked.add((r, c))
                
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            if (r, c) in blocked:
                continue
            nid = r * GRID_COLS + c
            lat = MIN_LAT + (r + 0.5) * lat_step
            lon = MIN_LON + (c + 0.5) * lon_step
            neighbors = []
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS and (nr, nc) not in blocked:
                    n2id = nr * GRID_COLS + nc
                    nlat = MIN_LAT + (nr + 0.5) * lat_step
                    nlon = MIN_LON + (nc + 0.5) * lon_step
                    dist = haversine_m(lat, lon, nlat, nlon)
                    neighbors.append((n2id, dist))
            graph[nid] = {"lat": lat, "lon": lon, "neighbors": neighbors}
    return graph

def _load_graph():
    """Loads graph from cache or builds fallback grid."""
    global _graph, _node_ids, _kdtree
    if GRAPH_CACHE.exists():
        try:
            with open(GRAPH_CACHE, "rb") as f:
                _graph = pickle.load(f)
        except Exception:
            _graph = None
            
    if _graph is None:
        try:
            import osmnx as ox
            G = ox.graph_from_bbox(MAX_LAT, MIN_LAT, MAX_LON, MIN_LON, network_type="drive")
            _graph = {}
            for node, data in G.nodes(data=True):
                _graph[node] = {"lat": data["y"], "lon": data["x"], "neighbors": []}
            for u, v, data in G.edges(data=True):
                dist = data.get("length", haversine_m(_graph[u]["lat"], _graph[u]["lon"], _graph[v]["lat"], _graph[v]["lon"]))
                _graph[u]["neighbors"].append((v, dist))
                if not G.is_directed():
                    _graph[v]["neighbors"].append((u, dist))
            with open(GRAPH_CACHE, "wb") as f:
                pickle.dump(_graph, f)
        except Exception:
            _graph = _build_grid_graph()
            try:
                with open(GRAPH_CACHE, "wb") as f:
                    pickle.dump(_graph, f)
            except Exception:
                pass
                
    _node_ids = list(_graph.keys())
    if HAS_SCIPY and _node_ids:
        coords = [[_graph[nid]["lat"], _graph[nid]["lon"]] for nid in _node_ids]
        _kdtree = KDTree(coords)

def _snap_to_node(lat: float, lon: float) -> int:
    """Finds nearest graph node to (lat, lon) using KDTree or linear scan."""
    global _kdtree, _node_ids, _graph
    if _kdtree is not None:
        _, idx = _kdtree.query([lat, lon])
        return _node_ids[idx]
        
    best_id = _node_ids[0] if _node_ids else 0
    best_dist = float("inf")
    for nid in _node_ids:
        node = _graph[nid]
        d = (node["lat"] - lat) ** 2 + (node["lon"] - lon) ** 2
        if d < best_dist:
            best_dist = d
            best_id = nid
    return best_id

def _astar(start_node: int, end_node: int, max_expansions: int = 5000) -> Optional[List[int]]:
    """
    Pure A* pathfinding using heapq with haversine distance heuristic.
    Returns list of node IDs forming optimal path, or None if unreachable.
    """
    if start_node not in _graph or end_node not in _graph:
        return None
    if start_node == end_node:
        return [start_node]

    end_lat = _graph[end_node]["lat"]
    end_lon = _graph[end_node]["lon"]

    # Priority queue stores tuples: (f_score, node_id)
    open_heap = [(0.0, start_node)]
    came_from: Dict[int, int] = {}
    g_score: Dict[int, float] = {start_node: 0.0}
    expansions = 0

    while open_heap and expansions < max_expansions:
        _, current = heapq.heappop(open_heap)
        expansions += 1

        if current == end_node:
            path = []
            curr = current
            while curr in came_from:
                path.append(curr)
                curr = came_from[curr]
            path.append(start_node)
            path.reverse()
            return path

        current_g = g_score[current]
        for neighbor, dist in _graph[current]["neighbors"]:
            tentative_g = current_g + dist
            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                h = haversine_m(_graph[neighbor]["lat"], _graph[neighbor]["lon"], end_lat, end_lon)
                heapq.heappush(open_heap, (tentative_g + h, neighbor))

    return None

def _route_sync(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[List[Tuple[float, float]], float]:
    """
    Computes route polyline and road distance (metres) synchronously.
    """
    global _graph
    if _graph is None:
        _load_graph()

    t0 = time.time()
    # Cache key rounded to ~50m
    cache_key = (round(lat1, 4), round(lon1, 4), round(lat2, 4), round(lon2, 4))
    if cache_key in _route_cache:
        polyline = _route_cache[cache_key]
        dist_m = sum(haversine_m(polyline[i][0], polyline[i][1], polyline[i+1][0], polyline[i+1][1]) for i in range(len(polyline)-1))
        return polyline, dist_m

    s = _snap_to_node(lat1, lon1)
    e = _snap_to_node(lat2, lon2)
    path_nodes = _astar(s, e)

    if path_nodes and len(path_nodes) > 1:
        polyline = [(lat1, lon1)] + [(_graph[n]["lat"], _graph[n]["lon"]) for n in path_nodes] + [(lat2, lon2)]
    else:
        # Fallback intermediate waypoint road path
        steps = 10
        polyline = [
            (lat1 + (lat2 - lat1) * i / steps + random.uniform(-0.0002, 0.0002),
             lon1 + (lon2 - lon1) * i / steps + random.uniform(-0.0002, 0.0002))
            for i in range(steps + 1)
        ]
        polyline[0] = (lat1, lon1)
        polyline[-1] = (lat2, lon2)

    total_dist_m = sum(
        haversine_m(polyline[i][0], polyline[i][1], polyline[i+1][0], polyline[i+1][1])
        for i in range(len(polyline) - 1)
    )

    elapsed_ms = (time.time() - t0) * 1000

    # Record latency metric in Redis
    try:
        from app.redis_client import get_sync_redis
        r = get_sync_redis()
        r.lpush("metrics:route_latency_ms", str(elapsed_ms))
        r.ltrim("metrics:route_latency_ms", 0, 99)
    except Exception:
        pass

    _route_cache[cache_key] = polyline
    if len(_route_cache) > 2000:
        del _route_cache[next(iter(_route_cache))]

    return polyline, total_dist_m

async def compute_route(lat1: float, lon1: float, lat2: float, lon2: float) -> List[Tuple[float, float]]:
    """Async wrapper: computes A* route in thread pool without blocking event loop."""
    loop = asyncio.get_running_loop()
    polyline, _ = await loop.run_in_executor(_executor, _route_sync, lat1, lon1, lat2, lon2)
    return polyline

def compute_route_sync(lat1: float, lon1: float, lat2: float, lon2: float) -> Tuple[List[Tuple[float, float]], float]:
    """Synchronous route computation."""
    return _route_sync(lat1, lon1, lat2, lon2)

def compute_road_eta_sec(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes estimated road transit time in seconds using A* road distance."""
    _, dist_m = _route_sync(lat1, lon1, lat2, lon2)
    return dist_m / AVG_RIDER_SPEED_MS

# Pre-load graph
_load_graph()
