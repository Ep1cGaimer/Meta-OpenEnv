import heapq
import random
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Core Data Models
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    from_node: str
    to_node: str
    base_travel_time: int
    road_type: str
    weather_sensitivity: float
    closure_threshold: str

WEATHER_LEVELS = ["Clear", "LightRain", "HeavyRain", "Storm"]
TRAFFIC_LEVELS = ["None", "Moderate", "Heavy", "Severe"]

WEATHER_PENALTY = {"Clear": 0, "LightRain": 5, "HeavyRain": 15, "Storm": 30}
TRAFFIC_PENALTY = {"None": 0, "Moderate": 10, "Heavy": 25, "Severe": 45}
WEATHER_RISK    = {"Clear": "Low", "LightRain": "Low", "HeavyRain": "Medium", "Storm": "High"}

def compute_edge_eta(edge: Edge, weather: str, traffic: str) -> int:
    w_penalty = int(edge.weather_sensitivity * WEATHER_PENALTY.get(weather, 0))
    t_penalty = TRAFFIC_PENALTY.get(traffic, 0)
    return edge.base_travel_time + w_penalty + t_penalty

def compute_edge_fuel(edge: Edge, weather: str, traffic: str) -> float:
    cost = float(edge.base_travel_time)
    if traffic in ("Heavy", "Severe"):
        cost *= 1.5
    if weather in ("HeavyRain", "Storm"):
        cost *= 1.5
    return round(cost, 2)

def is_edge_blocked(edge: Edge, weather: str) -> bool:
    threshold_idx = WEATHER_LEVELS.index(edge.closure_threshold)
    current_idx = WEATHER_LEVELS.index(weather)
    return current_idx >= threshold_idx

def get_risk_level(edge: Edge, weather: str, traffic: str) -> str:
    if is_edge_blocked(edge, weather):
        return "Blocked"
    w_risk = WEATHER_RISK.get(weather, "Low")
    if traffic in ("Heavy", "Severe") and w_risk in ("Medium", "High"):
        return "High"
    if traffic == "Severe" or w_risk == "High":
        return "High"
    if traffic == "Heavy" or w_risk == "Medium":
        return "Medium"
    return "Low"

def dijkstra_shortest_time(
    start: str,
    end: str,
    graph_nodes: list[str],
    adjacency: dict[str, list[Edge]],
    weather_map: dict[str, str],
    traffic_map: dict[str, str],
) -> int:
    dist = {n: 999999 for n in graph_nodes}
    dist[start] = 0
    pq = [(0, start)]

    while pq:
        d, node = heapq.heappop(pq)
        if node == end:
            return d
        if d > dist[node]:
            continue
        for edge in adjacency.get(node, []):
            w = weather_map.get(edge.to_node, "Clear")
            if is_edge_blocked(edge, w):
                continue
            t = traffic_map.get(f"{edge.from_node}->{edge.to_node}", "None")
            cost = d + compute_edge_eta(edge, w, t)
            if cost < dist[edge.to_node]:
                dist[edge.to_node] = cost
                heapq.heappush(pq, (cost, edge.to_node))
    return dist[end]

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@dataclass
class WeatherEvent:
    tick: int
    region: str
    condition: str

@dataclass
class TrafficEvent:
    tick: int
    edge_key: str
    severity: str
    duration: int

@dataclass
class ScenarioTemplate:
    name: str
    description: str
    start_node: str
    destination_node: str
    deadline_minutes: int
    initial_fuel: float
    initial_weather: dict[str, str]
    weather_schedule: list[WeatherEvent] = field(default_factory=list)
    traffic_schedule: list[TrafficEvent] = field(default_factory=list)

# ---------------------------------------------------------------------------
# 16-Node (4x4) Dynamic Grid Generator
# ---------------------------------------------------------------------------
#
# Grid layout:
#   N0  N1  N2  N3
#   N4  N5  N6  N7
#   N8  N9  N10 N11
#   N12 N13 N14 N15
#
# Weather regions:
#   NW = {N0, N1, N4, N5}   NE = {N2, N3, N6, N7}
#   SW = {N8, N9, N12, N13} SE = {N10, N11, N14, N15}
#
# Start: N0 (top-left)   Destination: N15 (bottom-right)
# Minimum hops: 6 (3 right + 3 down)

def generate_graph(seed: int):
    rng = random.Random(seed)

    # 4×4 Grid — 16 nodes
    graph_nodes = [f"N{i}" for i in range(16)]
    adjacency: dict[str, list[Edge]] = {n: [] for n in graph_nodes}
    node_to_region: dict[str, str] = {}
    weather_regions: dict[str, list[str]] = {"NW": [], "NE": [], "SW": [], "SE": []}

    def get_node(x: int, y: int) -> str:
        return f"N{y * 4 + x}"

    # Build regions (2×2 quadrants)
    for y in range(4):
        for x in range(4):
            node = get_node(x, y)
            if y < 2 and x < 2:
                r = "NW"
            elif y < 2 and x >= 2:
                r = "NE"
            elif y >= 2 and x < 2:
                r = "SW"
            else:
                r = "SE"
            weather_regions[r].append(node)
            node_to_region[node] = r

    # Build edges — bidirectional, seeded for consistency
    road_types = ["highway", "arterial", "mountain"]
    thresholds = ["HeavyRain", "Storm", "Storm"]
    for y in range(4):
        for x in range(4):
            node = get_node(x, y)
            neighbors = []
            if x > 0: neighbors.append(get_node(x-1, y))
            if x < 3: neighbors.append(get_node(x+1, y))
            if y > 0: neighbors.append(get_node(x, y-1))
            if y < 3: neighbors.append(get_node(x, y+1))

            for nx in neighbors:
                # Seed by sorted edge pair so bidirectional edges get same base cost
                edge_seed = tuple(sorted([node, nx]))
                local_rng = random.Random(hash(edge_seed) + seed)
                base_time = local_rng.randint(15, 30)
                rtype_idx = local_rng.randint(0, 2)
                rtype = road_types[rtype_idx]
                thresh = thresholds[rtype_idx]
                sens = local_rng.uniform(0.2, 0.8)

                adjacency[node].append(Edge(node, nx, base_time, rtype, sens, thresh))

    # Calculate baseline clear-weather optimal path N0→N15
    weather_map_clear = {n: "Clear" for n in graph_nodes}
    optimal_clear_time = dijkstra_shortest_time("N0", "N15", graph_nodes, adjacency, weather_map_clear, {})

    # Fuel budgets scaled per difficulty
    baseline_fuel = optimal_clear_time * 1.8 + 40.0

    all_tasks = {
        "1_easy_clear_path": ScenarioTemplate(
            name="1_easy_clear_path",
            description="Clear skies, light traffic. Find the shortest path from N0 to N15.",
            start_node="N0", destination_node="N15",
            deadline_minutes=int(optimal_clear_time * 2.5 + 80),
            initial_fuel=baseline_fuel * 1.8,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
        ),
        "2_medium_congestion": ScenarioTemplate(
            name="2_medium_congestion",
            description="Severe traffic on the central corridor. No directional hints — navigate by coordinates.",
            start_node="N0", destination_node="N15",
            deadline_minutes=int(optimal_clear_time * 1.6 + 30),
            initial_fuel=baseline_fuel * 1.3,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            traffic_schedule=[
                TrafficEvent(0, "N5->N6", "Severe", 999),
                TrafficEvent(0, "N9->N10", "Heavy", 999),
            ],
        ),
        "3_hard_strategic_wait": ScenarioTemplate(
            name="3_hard_strategic_wait",
            description="Storm blocks NW at start. No directional hints — wait for weather or find a path using coordinates.",
            start_node="N0", destination_node="N15",
            deadline_minutes=int(optimal_clear_time * 1.4 + 60),
            initial_fuel=baseline_fuel * 1.1,
            initial_weather={"NW": "Storm", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            weather_schedule=[WeatherEvent(40, "NW", "Clear")],
        ),
        "4_frontier_greedy_trap": ScenarioTemplate(
            name="4_frontier_greedy_trap",
            description="Storm hits SE mid-route. No direction hints. Greedy path is a trap — plan ahead.",
            start_node="N0", destination_node="N15",
            deadline_minutes=int(optimal_clear_time * 1.3 + 20),
            initial_fuel=baseline_fuel * 1.0,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            weather_schedule=[
                WeatherEvent(60, "SE", "Storm"),
                WeatherEvent(180, "SE", "Clear"),
            ],
        ),
    }

    return graph_nodes, adjacency, node_to_region, weather_regions, all_tasks

# Generate a default static instance for global imports
GRAPH_NODES, ADJACENCY, NODE_TO_REGION, WEATHER_REGIONS, ALL_TASKS = generate_graph(42)
