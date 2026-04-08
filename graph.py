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
# 25-Node Dynamic Grid Generator
# ---------------------------------------------------------------------------

def generate_graph(seed: int):
    rng = random.Random(seed)
    
    # 5x5 Grid
    graph_nodes = [f"N{i}" for i in range(25)]
    adjacency = {n: [] for n in graph_nodes}
    node_to_region = {}
    weather_regions = {"NW": [], "NE": [], "SW": [], "SE": []}

    def get_node(x, y):
        return f"N{y * 5 + x}"

    # Build regions
    for y in range(5):
        for x in range(5):
            node = get_node(x, y)
            if y < 3 and x < 3:
                r = "NW"
            elif y < 3 and x >= 3:
                r = "NE"
            elif y >= 3 and x < 3:
                r = "SW"
            else:
                r = "SE"
            weather_regions[r].append(node)
            node_to_region[node] = r

    # Build edges
    road_types = ["highway", "arterial", "mountain"]
    thresholds = ["HeavyRain", "Storm", "Storm"]
    for y in range(5):
        for x in range(5):
            node = get_node(x, y)
            neighbors = []
            if x > 0: neighbors.append(get_node(x-1, y))
            if x < 4: neighbors.append(get_node(x+1, y))
            if y > 0: neighbors.append(get_node(x, y-1))
            if y < 4: neighbors.append(get_node(x, y+1))
            
            for nx in neighbors:
                # To ensure Bidirectional edges have same base cost, we seed by edge tuple
                edge_seed = tuple(sorted([node, nx]))
                local_rng = random.Random(hash(edge_seed) + seed)
                base_time = local_rng.randint(15, 30)
                rtype_idx = local_rng.randint(0, 2)
                rtype = road_types[rtype_idx]
                thresh = thresholds[rtype_idx]
                sens = local_rng.uniform(0.2, 0.8)
                
                adjacency[node].append(Edge(node, nx, base_time, rtype, sens, thresh))

    # Calculate baseline Clear Weather optimal path to F (N24)
    weather_map_clear = {n: "Clear" for n in graph_nodes}
    optimal_clear_time = dijkstra_shortest_time("N0", "N24", graph_nodes, adjacency, weather_map_clear, {})
    
    # Very tight fuel budget: Baseline time * 1.5 + small buffer
    baseline_fuel = optimal_clear_time * 1.5 + 20.0

    all_tasks = {
        "1_easy_clear_path": ScenarioTemplate(
            name="1_easy_clear_path",
            description="25-Node Grid: Clear path to N24.",
            start_node="N0", destination_node="N24",
            deadline_minutes=optimal_clear_time + 40,
            initial_fuel=baseline_fuel,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
        ),
        "2_medium_congestion": ScenarioTemplate(
            name="2_medium_congestion",
            description="25-Node Grid: Severe traffic on the diagonal.",
            start_node="N0", destination_node="N24",
            deadline_minutes=optimal_clear_time + 60,
            initial_fuel=baseline_fuel + 30,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            traffic_schedule=[TrafficEvent(0, "N6->N7", "Severe", 999)],
        ),
        "3_hard_strategic_wait": ScenarioTemplate(
            name="3_hard_strategic_wait",
            description="25-Node Grid: Storm clears up halfway.",
            start_node="N0", destination_node="N24",
            deadline_minutes=optimal_clear_time + 80,
            initial_fuel=baseline_fuel + 20,
            initial_weather={"NW": "Storm", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            weather_schedule=[WeatherEvent(40, "NW", "Clear")],
        ),
        "4_frontier_greedy_trap": ScenarioTemplate(
            name="4_frontier_greedy_trap",
            description="25-Node Grid: Approaching storm traps greedy routing.",
            start_node="N0", destination_node="N24",
            deadline_minutes=optimal_clear_time + 50,
            initial_fuel=baseline_fuel,
            initial_weather={"NW": "Clear", "NE": "Clear", "SW": "Clear", "SE": "Clear"},
            weather_schedule=[WeatherEvent(30, "SE", "Storm"), WeatherEvent(180, "SE", "Clear")],
        ),
        "5_impossible_dynamic_maze": ScenarioTemplate(
            name="5_impossible_dynamic_maze",
            description="25-Node Grid: Fuel is critical and routing requires exact waiting.",
            start_node="N0", destination_node="N24",
            deadline_minutes=optimal_clear_time + 75,
            initial_fuel=baseline_fuel + 5,  # Very tight fuel!
            initial_weather={"NW": "Clear", "NE": "Storm", "SW": "Storm", "SE": "Storm"},
            weather_schedule=[WeatherEvent(60, "SE", "Clear")],
            traffic_schedule=[TrafficEvent(0, "N5->N10", "Severe", 100)],
        ),
    }

    return graph_nodes, adjacency, node_to_region, weather_regions, all_tasks

# Generate a default static instance for global imports to satisfy legacy code
GRAPH_NODES, ADJACENCY, NODE_TO_REGION, WEATHER_REGIONS, ALL_TASKS = generate_graph(42)
