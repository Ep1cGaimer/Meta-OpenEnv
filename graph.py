"""
Graph topology, weather/traffic simulation, and scenario templates.

The graph represents a small road network where each edge has properties
that determine how weather and traffic affect travel. Scenarios are
deterministic schedules seeded per-episode for reproducible grading.
"""

import heapq
import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Edge and graph definitions
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    from_node: str
    to_node: str
    base_travel_time: int       # minutes
    road_type: str              # highway, arterial, mountain, coastal
    weather_sensitivity: float  # 0.0-1.0, how much weather degrades this edge
    closure_threshold: str      # weather level that blocks this edge entirely

GRAPH_NODES = ["A", "B", "C", "D", "E", "F", "G", "H"]

# The graph is intentionally structured:
#   - A->B->D->F is the short/fast corridor but weather-sensitive (highway, coastal)
#   - A->C->E->G->H->F is the long/safe corridor (arterial, inland)
#   - Multiple branch points create real tradeoffs
GRAPH_EDGES = [
    # Short risky corridor (highway/coastal — storm-sensitive)
    Edge("A", "B", 25, "highway",  0.7, "Storm"),
    Edge("B", "A", 25, "highway",  0.7, "Storm"),
    Edge("B", "D", 30, "coastal",  0.8, "HeavyRain"),
    Edge("D", "B", 30, "coastal",  0.8, "HeavyRain"),
    Edge("D", "F", 35, "highway",  0.6, "Storm"),
    Edge("F", "D", 35, "highway",  0.6, "Storm"),

    # Long safe corridor (arterial/inland — weather-resistant)
    Edge("A", "C", 30, "arterial", 0.2, "Storm"),
    Edge("C", "A", 30, "arterial", 0.2, "Storm"),
    Edge("C", "E", 25, "arterial", 0.3, "Storm"),
    Edge("E", "C", 25, "arterial", 0.3, "Storm"),
    Edge("E", "G", 20, "arterial", 0.2, "Storm"),
    Edge("G", "E", 20, "arterial", 0.2, "Storm"),
    Edge("G", "H", 20, "arterial", 0.1, "Storm"),
    Edge("H", "G", 20, "arterial", 0.1, "Storm"),
    Edge("H", "F", 25, "arterial", 0.2, "Storm"),
    Edge("F", "H", 25, "arterial", 0.2, "Storm"),

    # Cross-links (create branch decision points)
    Edge("B", "E", 35, "mountain", 0.5, "HeavyRain"),
    Edge("E", "B", 35, "mountain", 0.5, "HeavyRain"),
    Edge("C", "D", 40, "arterial", 0.4, "Storm"),
    Edge("D", "C", 40, "arterial", 0.4, "Storm"),
    Edge("E", "F", 45, "mountain", 0.6, "Storm"),
    Edge("F", "E", 45, "mountain", 0.6, "Storm"),
]


def build_adjacency() -> dict[str, list[Edge]]:
    """Build adjacency list from edge definitions."""
    adj: dict[str, list[Edge]] = {n: [] for n in GRAPH_NODES}
    for e in GRAPH_EDGES:
        adj[e.from_node].append(e)
    return adj


ADJACENCY = build_adjacency()

# Weather regions — nodes sharing weather patterns
WEATHER_REGIONS = {
    "coastal":  ["B", "D"],
    "inland":   ["C", "E", "G"],
    "highland": ["A", "H"],
    "southern": ["F"],
}

# Reverse mapping: node -> region
NODE_TO_REGION = {}
for region, nodes in WEATHER_REGIONS.items():
    for node in nodes:
        NODE_TO_REGION[node] = region

WEATHER_LEVELS = ["Clear", "LightRain", "HeavyRain", "Storm"]
TRAFFIC_LEVELS = ["None", "Moderate", "Heavy", "Severe"]


# ---------------------------------------------------------------------------
# Weather and traffic penalty calculation
# ---------------------------------------------------------------------------

WEATHER_PENALTY = {"Clear": 0, "LightRain": 5, "HeavyRain": 15, "Storm": 30}
TRAFFIC_PENALTY = {"None": 0, "Moderate": 10, "Heavy": 25, "Severe": 45}
WEATHER_RISK    = {"Clear": "Low", "LightRain": "Low", "HeavyRain": "Medium", "Storm": "High"}


def compute_edge_eta(edge: Edge, weather: str, traffic: str) -> int:
    """Total travel time for an edge given current conditions."""
    w_penalty = int(edge.weather_sensitivity * WEATHER_PENALTY.get(weather, 0))
    t_penalty = TRAFFIC_PENALTY.get(traffic, 0)
    return edge.base_travel_time + w_penalty + t_penalty


def is_edge_blocked(edge: Edge, weather: str) -> bool:
    """Check if weather has crossed this edge's closure threshold."""
    threshold_idx = WEATHER_LEVELS.index(edge.closure_threshold)
    current_idx = WEATHER_LEVELS.index(weather)
    return current_idx >= threshold_idx


def get_risk_level(edge: Edge, weather: str, traffic: str) -> str:
    """Determine overall risk for an edge."""
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


# ---------------------------------------------------------------------------
# Dijkstra — used to compute safe baseline optimal path for scoring
# ---------------------------------------------------------------------------

def dijkstra_shortest_time(
    start: str,
    end: str,
    weather_map: dict[str, str],
    traffic_map: dict[str, str],
) -> int:
    """
    Shortest arrival time from start to end given current conditions.
    Returns the time in minutes, or 999999 if unreachable.
    """
    dist = {n: 999999 for n in GRAPH_NODES}
    dist[start] = 0
    pq = [(0, start)]

    while pq:
        d, node = heapq.heappop(pq)
        if node == end:
            return d
        if d > dist[node]:
            continue
        for edge in ADJACENCY.get(node, []):
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
# Scenario templates — deterministic weather/traffic schedules
# ---------------------------------------------------------------------------

@dataclass
class WeatherEvent:
    tick: int        # simulation minute when this takes effect
    region: str
    condition: str   # one of WEATHER_LEVELS

@dataclass
class TrafficEvent:
    tick: int
    edge_key: str    # e.g. "B->D"
    severity: str    # one of TRAFFIC_LEVELS
    duration: int    # how many minutes this lasts

@dataclass
class ScenarioTemplate:
    name: str
    description: str
    start_node: str
    destination_node: str
    deadline_minutes: int
    initial_weather: dict[str, str]       # region -> condition
    weather_schedule: list[WeatherEvent] = field(default_factory=list)
    traffic_schedule: list[TrafficEvent] = field(default_factory=list)


# --- Task 1: Congestion Avoidance ---
# The short corridor (A->B->D->F) gets severe traffic on B->D.
# Weather is mostly fine. Agent should detour through C or E.
TASK_CONGESTION = ScenarioTemplate(
    name="congestion_avoidance",
    description="Heavy traffic blocks the fast corridor. Find an efficient detour.",
    start_node="A",
    destination_node="F",
    deadline_minutes=180,
    initial_weather={
        "coastal": "Clear",
        "inland": "Clear",
        "highland": "Clear",
        "southern": "Clear",
    },
    weather_schedule=[
        # Mild rain develops on the coast at minute 60, but nothing critical
        WeatherEvent(60, "coastal", "LightRain"),
        WeatherEvent(120, "coastal", "Clear"),
    ],
    traffic_schedule=[
        # Severe congestion on the fast route almost immediately
        TrafficEvent(0,  "B->D", "Severe", 150),
        # Moderate backup on D->F as well
        TrafficEvent(20, "D->F", "Heavy", 100),
    ],
)

# --- Task 2: Severe Weather Detour ---
# Storm hits the coastal corridor, blocking B->D entirely.
# Agent must choose the safe inland route despite it being longer.
TASK_WEATHER = ScenarioTemplate(
    name="severe_weather_detour",
    description="Storm blocks the coastal fast route. Prioritize safety over speed.",
    start_node="A",
    destination_node="F",
    deadline_minutes=200,
    initial_weather={
        "coastal": "LightRain",
        "inland": "Clear",
        "highland": "Clear",
        "southern": "Clear",
    },
    weather_schedule=[
        # Storm develops on coast at minute 20 — blocks B->D (closure_threshold=HeavyRain)
        WeatherEvent(20, "coastal", "HeavyRain"),
        WeatherEvent(40, "coastal", "Storm"),
        WeatherEvent(130, "coastal", "HeavyRain"),
        WeatherEvent(160, "coastal", "LightRain"),
    ],
    traffic_schedule=[
        # Some moderate traffic on the inland route to add realism
        TrafficEvent(30, "C->E", "Moderate", 60),
    ],
)

# --- Task 3: Strategic Waiting ---
# The best route (B->D->F) is temporarily degraded by heavy rain.
# Rain clears within 20-30 minutes. Waiting is better than a long detour.
TASK_WAITING = ScenarioTemplate(
    name="strategic_waiting",
    description="Best route temporarily degraded. Waiting for conditions to clear is optimal.",
    start_node="A",
    destination_node="F",
    deadline_minutes=180,
    initial_weather={
        "coastal": "HeavyRain",
        "inland": "Clear",
        "highland": "Clear",
        "southern": "Clear",
    },
    weather_schedule=[
        # Rain clears at minute 30 — the agent starts at A, so if it waits ~20 min it can
        # take the fast route safely
        WeatherEvent(30, "coastal", "LightRain"),
        WeatherEvent(50, "coastal", "Clear"),
    ],
    traffic_schedule=[
        TrafficEvent(0, "B->D", "Moderate", 40),
        TrafficEvent(40, "B->D", "None", 999),
    ],
)

ALL_TASKS = {
    "congestion_avoidance": TASK_CONGESTION,
    "severe_weather_detour": TASK_WEATHER,
    "strategic_waiting": TASK_WAITING,
}
