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

def _interpolate_segment(p1: Tuple[float, float], p2: Tuple[float, float], max_step_m: float = 75.0) -> List[Tuple[float, float]]:
    """Densely interpolates points along a road segment to follow physical streets."""
    dist = haversine_m(p1[0], p1[1], p2[0], p2[1])
    if dist <= max_step_m:
        return [p1, p2]
    num_steps = max(2, int(dist / max_step_m))
    pts = []
    for i in range(num_steps):
        frac = i / num_steps
        lat = p1[0] + (p2[0] - p1[0]) * frac
        lon = p1[1] + (p2[1] - p1[1]) * frac
        pts.append((round(lat, 6), round(lon, 6)))
    pts.append(p2)
    return pts

BANGALORE_CORRIDORS = [
    # 1. Hosur Road (Richmond Circle -> Shanti Nagar -> Adugodi -> Dairy Circle -> Silk Board -> Electronic City)
    [
        (12.9602, 77.5975),  # Richmond Circle
        (12.9550, 77.5985),  # Shanti Nagar Bus Stand
        (12.9490, 77.6010),  # Langford Town / Hosur Rd
        (12.9440, 77.6040),  # Anepalya Junction
        (12.9385, 77.6080),  # Adugodi Signal
        (12.9340, 77.6110),  # Forum Mall / Dairy Circle
        (12.9270, 77.6150),  # SG Palya Junction
        (12.9220, 77.6190),  # Madiwala Checkpost
        (12.9175, 77.6235),  # Silk Board Junction
        (12.9080, 77.6280),  # Bommanahalli
        (12.8900, 77.6400),  # Kudlu Gate
        (12.8452, 77.6602),  # Electronic City Phase 1
    ],
    # 2. Koramangala 80 Feet & 100 Feet Roads (Dairy Circle -> 7th Block -> Sony World -> Ejipura)
    [
        (12.9340, 77.6110),  # Dairy Circle / Forum
        (12.9345, 77.6170),  # Koramangala 7th Block
        (12.9352, 77.6245),  # Sony World Signal (Meghana Foods hub)
        (12.9370, 77.6290),  # 80 Feet Road / 4th Block
        (12.9390, 77.6320),  # Maharaja Signal / 100 Feet Rd
    ],
    # 3. Intermediate Ring Road (Inner Ring Road: Sony World -> Ejipura -> Domlur)
    [
        (12.9352, 77.6245),  # Sony World Signal
        (12.9410, 77.6270),  # Ejipura Signal
        (12.9460, 77.6300),  # Srinivagilu
        (12.9510, 77.6335),  # National Games Village
        (12.9560, 77.6360),  # Embassy GolfLinks Entrance
        (12.9610, 77.6385),  # Domlur Flyover / Inner Ring Road junction
    ],
    # 4. Indiranagar 100 Feet Road (Domlur Flyover -> 12th Main -> Toit -> CMH Rd -> Old Madras Rd)
    [
        (12.9610, 77.6385),  # Domlur Flyover
        (12.9670, 77.6405),  # 100 Feet Rd (Doopanahalli)
        (12.9720, 77.6415),  # 12th Main Junction
        (12.9784, 77.6408),  # Toit Brewpub / 100 Feet Rd
        (12.9820, 77.6415),  # CMH Road Junction
        (12.9860, 77.6430),  # Old Madras Road / Indiranagar Metro
    ],
    # 5. Old Airport Road (Trinity Circle -> Domlur -> HAL -> Marathahalli)
    [
        (12.9725, 77.6200),  # Trinity Circle / MG Road end
        (12.9670, 77.6280),  # Victoria Layout / Command Hospital
        (12.9610, 77.6385),  # Domlur Junction
        (12.9580, 77.6520),  # Manipal Hospital Old Airport Rd
        (12.9550, 77.6650),  # HAL Airport Heritage Centre
        (12.9560, 77.6850),  # ISRO Vimanapura
        (12.9569, 77.7011),  # Marathahalli Bridge (Punjabi Rasoi hub)
    ],
    # 6. Marathahalli - Whitefield Corridor
    [
        (12.9569, 77.7011),  # Marathahalli Bridge
        (12.9580, 77.7150),  # Kundalahalli Gate
        (12.9630, 77.7300),  # ITPL Main Road
        (12.9698, 77.7500),  # Whitefield (Windmills Craftworks hub)
    ],
    # 7. Sarjapur Road & HSR Layout Corridor
    [
        (12.9352, 77.6245),  # Sony World Koramangala
        (12.9280, 77.6310),  # Jakkasandra
        (12.9230, 77.6450),  # Agara Lake Junction
        (12.9150, 77.6350),  # HSR BDA Complex
        (12.9116, 77.6389),  # HSR 27th Main (Udupi Park hub)
        (12.9175, 77.6235),  # Silk Board Junction
    ],
    # 8. BTM Layout & Outer Ring Road South
    [
        (12.9175, 77.6235),  # Silk Board
        (12.9160, 77.6160),  # BTM 1st Stage
        (12.9166, 77.6101),  # BTM 2nd Stage (Babu Biryani hub)
        (12.9175, 77.6030),  # Jayadeva Flyover (Bannerghatta Rd)
        (12.9340, 77.6110),  # Dairy Circle (Bannerghatta Rd north)
    ],
    # 9. Jayanagar & Basavanagudi Corridor
    [
        (12.9175, 77.6030),  # Jayadeva Flyover
        (12.9240, 77.5930),  # Jayanagar 9th Block
        (12.9308, 77.5838),  # Jayanagar 4th Block Complex (Maiyas hub)
        (12.9350, 77.5790),  # South End Circle
        (12.9406, 77.5738),  # Basavanagudi / Bugle Rock (Kamat hub)
        (12.9500, 77.5750),  # VV Puram Food Street
        (12.9600, 77.5800),  # KR Market / Town Hall
        (12.9660, 77.5880),  # Corporation Circle
    ],
    # 10. JP Nagar Corridor
    [
        (12.9175, 77.6030),  # Jayadeva
        (12.9100, 77.5950),  # JP Nagar 2nd Phase
        (12.9063, 77.5857),  # JP Nagar 6th Phase (Black Pearl hub)
        (12.9020, 77.5750),  # Sarakki Signal
    ],
    # 11. Central Bengaluru / MG Road / Richmond Town Arteries
    [
        (12.9660, 77.5880),  # Corporation Circle
        (12.9730, 77.5870),  # KR Circle / Cubbon Park
        (12.9790, 77.5910),  # Vidhana Soudha / High Court
        (12.9760, 77.6010),  # St. Mark's Road
        (12.9757, 77.6068),  # MG Road (Empire hub)
        (12.9730, 77.6120),  # Mayo Hall / Brigade Road
        (12.9725, 77.6200),  # Trinity Circle
        (12.9640, 77.6010),  # Richmond Town (Corner House hub)
        (12.9602, 77.5975),  # Richmond Circle
    ],
    # 12. Malleshwaram & Hebbal North Corridor
    [
        (12.9790, 77.5910),  # Vidhana Soudha
        (12.9860, 77.5820),  # Race Course Road
        (12.9930, 77.5760),  # Seshadripuram
        (13.0035, 77.5710),  # Malleshwaram 8th Cross (Vidyarthi Bhavan hub)
        (13.0120, 77.5700),  # Malleshwaram 18th Cross
        (13.0180, 77.5800),  # Sadashivanagar / Bellary Rd
        (13.0250, 77.5880),  # Mekhri Circle
        (13.0358, 77.5970),  # Hebbal Flyover (Hebbal Lake Bistro hub)
    ],
    # 13. Cross Arteries: Richmond Town -> Shanti Nagar -> Adugodi -> Koramangala
    [
        (12.9640, 77.6010),  # Richmond Town
        (12.9580, 77.6030),  # Hosur Road / Richmond Rd
        (12.9490, 77.6010),  # Langford Town
        (12.9385, 77.6080),  # Adugodi Junction
        (12.9352, 77.6245),  # Sony World Koramangala via 80ft road
    ],
    # 14. Halasuru / Ulsoor Lake -> Indiranagar
    [
        (12.9725, 77.6200),  # Trinity Circle
        (12.9780, 77.6250),  # Ulsoor Lake
        (12.9820, 77.6350),  # CMH Road West
        (12.9784, 77.6408),  # Toit Indiranagar
    ],
    # 15. Domlur -> Koramangala connector (EGL / Inner Ring Road south)
    [
        (12.9610, 77.6385),  # Domlur Flyover
        (12.9560, 77.6360),  # Embassy GolfLinks
        (12.9510, 77.6335),  # National Games Village
        (12.9460, 77.6300),  # Srinivagilu
        (12.9410, 77.6270),  # Ejipura
        (12.9390, 77.6320),  # 100 Feet Rd / 4th Block
        (12.9352, 77.6245),  # Sony World Koramangala
    ],
    # 16. Silk Board -> Electronic City direct (NH44 extended)
    [
        (12.9175, 77.6235),  # Silk Board
        (12.9080, 77.6280),  # Bommanahalli
        (12.8900, 77.6400),  # Kudlu Gate
        (12.8700, 77.6500),  # Hosa Road Junction
        (12.8600, 77.6560),  # Electronic City Phase 2
        (12.8452, 77.6602),  # Electronic City Phase 1
    ],
    # 17. Whitefield -> Marathahalli -> HAL (reverse leg for eastbound routing)
    [
        (12.9698, 77.7500),  # Whitefield
        (12.9630, 77.7300),  # ITPL Main Road
        (12.9580, 77.7150),  # Kundalahalli Gate
        (12.9569, 77.7011),  # Marathahalli Bridge
        (12.9560, 77.6850),  # ISRO Vimanapura
        (12.9550, 77.6650),  # HAL Airport Heritage
    ],
    # 18. MG Road -> Cubbon Park -> KR Circle (central east-west connector)
    [
        (12.9757, 77.6068),  # MG Road Empire
        (12.9730, 77.6120),  # Mayo Hall
        (12.9725, 77.6200),  # Trinity Circle
        (12.9760, 77.6010),  # St Mark's Road
        (12.9730, 77.5870),  # KR Circle
        (12.9660, 77.5880),  # Corporation Circle
    ],
    # 19. HSR - Sarjapur - Bellandur link
    [
        (12.9116, 77.6389),  # HSR BDA
        (12.9150, 77.6350),  # HSR 27th Main
        (12.9230, 77.6450),  # Agara Lake
        (12.9280, 77.6520),  # Bellandur Junction
        (12.9350, 77.6600),  # Sarjapur Road Flyover
        (12.9400, 77.6680),  # Iblur Junction
        (12.9500, 77.6650),  # Kadubeesanahalli
        (12.9569, 77.7011),  # Marathahalli Bridge
    ],
    # 20. JP Nagar -> Bannerghatta -> BTM connector
    [
        (12.9020, 77.5750),  # Sarakki Signal JP Nagar
        (12.9050, 77.5900),  # JP Nagar 1st Phase
        (12.9100, 77.6000),  # Jayadeva adjacent
        (12.9160, 77.6160),  # BTM 1st Stage
        (12.9175, 77.6235),  # Silk Board
    ],
]

def _build_grid_graph():
    """Build a realistic connected road network graph over Bangalore connecting all hubs."""
    graph = {}
    nodes = []

    # 1. Expand all corridors with dense road points (~70m apart)
    corridor_nodes = []
    node_id = 0
    for corr in BANGALORE_CORRIDORS:
        chain = []
        for i in range(len(corr) - 1):
            sub_pts = _interpolate_segment(corr[i], corr[i+1], max_step_m=75.0)
            if i > 0:
                sub_pts = sub_pts[1:]  # avoid duplicating segment join
            for pt in sub_pts:
                graph[node_id] = {"lat": pt[0], "lon": pt[1], "neighbors": []}
                nodes.append((node_id, pt[0], pt[1]))
                chain.append(node_id)
                node_id += 1
        corridor_nodes.append(chain)

    # 2. Add sequential edges within each corridor
    for chain in corridor_nodes:
        for i in range(len(chain) - 1):
            u, v = chain[i], chain[i+1]
            dist = haversine_m(graph[u]["lat"], graph[u]["lon"], graph[v]["lat"], graph[v]["lon"])
            graph[u]["neighbors"].append((v, dist))
            graph[v]["neighbors"].append((u, dist))

    # 3. Intersect corridors: connect nodes that are close (< 100m) to allow street turns
    for i in range(len(nodes)):
        u, u_lat, u_lon = nodes[i]
        for j in range(i + 1, len(nodes)):
            v, v_lat, v_lon = nodes[j]
            d = haversine_m(u_lat, u_lon, v_lat, v_lon)
            if d <= 90.0:  # Intersection threshold
                graph[u]["neighbors"].append((v, d))
                graph[v]["neighbors"].append((u, d))

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
    elif s == e and s in _graph:
        polyline = [(lat1, lon1), (_graph[s]["lat"], _graph[s]["lon"]), (lat2, lon2)]
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
