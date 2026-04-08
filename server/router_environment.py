"""
Supply Chain Logistics Router environment implementation.

The simulator models a truck navigating a deterministic road graph under
scheduled weather and traffic changes. Episodes are seeded so grading remains
reproducible across runs.
"""

import copy
import os
import random
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import RouteOption, RouterAction, RouterObservation
    from ..graph import (
        ADJACENCY,
        ALL_TASKS,
        GRAPH_NODES,
        NODE_TO_REGION,
        TRAFFIC_PENALTY,
        WEATHER_LEVELS,
        ScenarioTemplate,
        compute_edge_eta,
        dijkstra_shortest_time,
        get_risk_level,
        is_edge_blocked,
    )
except ImportError:
    from models import RouteOption, RouterAction, RouterObservation
    from graph import (
        ADJACENCY,
        ALL_TASKS,
        GRAPH_NODES,
        NODE_TO_REGION,
        TRAFFIC_PENALTY,
        WEATHER_LEVELS,
        ScenarioTemplate,
        compute_edge_eta,
        dijkstra_shortest_time,
        get_risk_level,
        is_edge_blocked,
    )


class RouterEnvironment(Environment):
    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)

        self.current_node = ""
        self.destination = ""
        self.deadline = 0
        self.elapsed = 0
        self.arrived = False
        self.failed = False
        self.task_name = ""
        self.path_history: list[str] = []
        self.safety_penalties: float = 0.0
        self.last_action_summary = ""
        self.last_action_error = ""

        self.weather_map: dict[str, str] = {}
        self.traffic_map: dict[str, str] = {}

        self.scenario: ScenarioTemplate | None = None
        self.baseline_time: int = 0
        self.rng = random.Random(42)

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        task_name: str | None = None,
    ) -> RouterObservation:
        resolved_task_name = task_name or os.environ.get(
            "TASK_NAME", "congestion_avoidance"
        )
        resolved_seed = (
            seed if seed is not None else int(os.environ.get("EPISODE_SEED", "42"))
        )

        # 1. Initialize the Random Number Generator with the seed
        self.rng = random.Random(resolved_seed)

        # 2. Fetch the base hard-coded template
        base_scenario = ALL_TASKS.get(resolved_task_name, list(ALL_TASKS.values())[0])

        # 3. CRITICAL: Deep copy the scenario so we don't mutate the global templates!
        self.scenario = copy.deepcopy(base_scenario)
        self.task_name = self.scenario.name

        # 4. APPLY SEEDED RANDOMNESS (JITTER) TO WEATHER
        # Shift weather events backward or forward by up to 10 minutes
        for event in self.scenario.weather_schedule:
            jitter = self.rng.randint(-10, 10)
            # Ensure time doesn't drop below 0
            event.tick = max(0, event.tick + jitter) 

        # 5. APPLY SEEDED RANDOMNESS (JITTER) TO TRAFFIC
        for event in self.scenario.traffic_schedule:
            start_jitter = self.rng.randint(-5, 15)
            duration_jitter = self.rng.randint(-20, 20)
            
            event.tick = max(0, event.tick + start_jitter)
            
            # If duration is 999 (permanent), leave it alone. Otherwise, jitter it.
            if event.duration < 900: 
                event.duration = max(10, event.duration + duration_jitter)

        # 6. Proceed with the rest of the standard reset logic
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        self.current_node = self.scenario.start_node
        self.destination = self.scenario.destination_node
        self.deadline = self.scenario.deadline_minutes
        self.elapsed = 0
        self.arrived = False
        self.failed = False
        self.path_history = [self.current_node]
        self.safety_penalties = 0.0
        self.last_action_summary = "Episode started."
        self.last_action_error = ""

        self.weather_map = dict(self.scenario.initial_weather)
        self.traffic_map = {}
        self._apply_schedules()

        node_weather = self._get_node_weather_map()
        baseline_initial = dijkstra_shortest_time(
            self.current_node, self.destination, node_weather, self.traffic_map
        )

        # Also compute baseline under clear conditions — accounts for scenarios
        # where waiting for weather to clear yields a faster optimal path
        clear_weather = {node: "Clear" for node in GRAPH_NODES}
        baseline_clear = dijkstra_shortest_time(
            self.current_node, self.destination, clear_weather, {}
        )
        self.baseline_time = min(baseline_initial, baseline_clear)

        return self._build_observation(reward=0.0, done=False)
    
    def step(self, action: RouterAction) -> RouterObservation:
        self._state.step_count += 1

        if self.arrived or self.failed:
            return self._build_observation(reward=0.0, done=True)

        if action.action_type == "move":
            return self._handle_move(action.target_node)
        if action.action_type == "wait":
            return self._handle_wait(action.wait_minutes)

        self.last_action_error = f"Invalid action type: '{action.action_type}'"
        self.last_action_summary = f"{self.last_action_error}. No action taken."
        return self._build_observation(reward=0.0, done=False)

    def _handle_move(self, target: str) -> RouterObservation:
        edges = ADJACENCY.get(self.current_node, [])
        edge = next((edge for edge in edges if edge.to_node == target), None)
        self.last_action_error = ""

        if edge is None:
            self.last_action_error = (
                f"Invalid move: '{target}' is not adjacent to {self.current_node}. "
                f"Valid targets: {[edge.to_node for edge in edges]}"
            )
            self.last_action_summary = self.last_action_error
            return self._build_observation(reward=0.02, done=False)

        target_weather = self._node_weather(target)
        if is_edge_blocked(edge, target_weather):
            self.last_action_error = (
                f"Route {self.current_node}->{target} is BLOCKED due to {target_weather}. "
                f"Choose another route or wait."
            )
            self.last_action_summary = self.last_action_error
            return self._build_observation(reward=0.02, done=False)

        traffic = self.traffic_map.get(f"{self.current_node}->{target}", "None")
        travel_time = compute_edge_eta(edge, target_weather, traffic)
        self.elapsed += travel_time
        self._apply_schedules()

        risk = get_risk_level(edge, target_weather, traffic)
        if risk == "High":
            self.safety_penalties += 0.3
        elif risk == "Medium":
            self.safety_penalties += 0.1

        self.current_node = target
        self.path_history.append(target)
        self.last_action_summary = (
            f"Moved {self.path_history[-2]}->{target} in {travel_time} min. "
            f"Weather: {target_weather}, Traffic: {traffic}."
        )

        if self.current_node == self.destination:
            self.arrived = True
            return self._build_observation(
                reward=self._compute_final_score(), done=True
            )

        if self.elapsed >= self.deadline:
            self.failed = True
            return self._build_observation(reward=0.0, done=True)

        step_reward = max(
            0.0, min(0.1, (self.deadline - self.elapsed) / self.deadline * 0.1)
        )
        return self._build_observation(reward=step_reward, done=False)

    def _handle_wait(self, minutes: int) -> RouterObservation:
        self.last_action_error = ""

        if minutes not in (10, 20):
            minutes = 10

        self.elapsed += minutes
        self._apply_schedules()
        self.last_action_summary = f"Waited {minutes} min at {self.current_node}."

        if self.elapsed >= self.deadline:
            self.failed = True
            return self._build_observation(reward=0.0, done=True)

        step_reward = max(
            0.0, min(0.05, (self.deadline - self.elapsed) / self.deadline * 0.05)
        )
        return self._build_observation(reward=step_reward, done=False)

    def _build_observation(self, reward: float, done: bool) -> RouterObservation:
        route_options = []
        action_list = []
        alerts: list[str] = []

        for edge in ADJACENCY.get(self.current_node, []):
            weather = self._node_weather(edge.to_node)
            traffic = self.traffic_map.get(f"{edge.from_node}->{edge.to_node}", "None")
            blocked = is_edge_blocked(edge, weather)
            risk = get_risk_level(edge, weather, traffic)
            eta = compute_edge_eta(edge, weather, traffic) if not blocked else 9999
            status = (
                "blocked"
                if blocked
                else ("degraded" if risk in ("Medium", "High") else "open")
            )
            trend = self._get_trend(edge.to_node)

            route_options.append(
                RouteOption(
                    to_node=edge.to_node,
                    base_travel_time_minutes=edge.base_travel_time,
                    traffic_delay_minutes=TRAFFIC_PENALTY.get(traffic, 0),
                    weather=weather,
                    risk_level=risk,
                    edge_status=status,
                    eta_to_next_node=eta,
                    trend=trend,
                )
            )

            if not blocked:
                action_list.append(f"move_to({edge.to_node})")
            if risk == "High":
                alerts.append(
                    f"High risk on {self.current_node}->{edge.to_node}: "
                    f"{weather}, traffic {traffic}"
                )
            if blocked:
                alerts.append(
                    f"BLOCKED: {self.current_node}->{edge.to_node} due to {weather}"
                )

        action_list.extend(["wait(10)", "wait(20)"])
        message = self._render_message(route_options, alerts)

        return RouterObservation(
            truck_location=self.current_node,
            destination=self.destination,
            time_remaining_minutes=max(0, self.deadline - self.elapsed),
            elapsed_minutes=self.elapsed,
            route_options=route_options,
            available_actions=action_list,
            last_action_summary=self.last_action_summary,
            last_action_error=self.last_action_error,
            alerts=alerts,
            message=message,
            done=done,
            reward=round(max(0.0, min(1.0, reward)), 4),
            metadata={
                "task_name": self.task_name,
                "deadline_minutes": self.deadline,
                "baseline_time_minutes": self.baseline_time,
            },
        )

    def _render_message(self, routes: list[RouteOption], alerts: list[str]) -> str:
        lines = [
            f"Truck at {self.current_node}. Destination: {self.destination}. "
            f"Time remaining: {max(0, self.deadline - self.elapsed)} min.",
            "",
            "Route options:",
        ]
        for index, route in enumerate(routes, 1):
            if route.edge_status == "blocked":
                lines.append(
                    f"  {index}. {self.current_node}->{route.to_node} | "
                    f"BLOCKED ({route.weather})"
                )
            else:
                delay = (
                    f" (+{route.traffic_delay_minutes} min traffic)"
                    if route.traffic_delay_minutes
                    else ""
                )
                lines.append(
                    f"  {index}. {self.current_node}->{route.to_node} | "
                    f"ETA {route.eta_to_next_node} min{delay} | "
                    f"weather {route.weather} | risk {route.risk_level} | "
                    f"trend {route.trend}"
                )

        lines.append("")
        lines.append("Additional actions: wait(10), wait(20)")

        if alerts:
            lines.append("")
            lines.append("Alerts:")
            for alert in alerts:
                lines.append(f"  !! {alert}")

        lines.append("")
        lines.append(f"Last action: {self.last_action_summary}")
        if self.last_action_error:
            lines.append(f"Last action error: {self.last_action_error}")
        lines.append(f"Path history: {' -> '.join(self.path_history)}")

        return "\n".join(lines)

    def _compute_final_score(self) -> float:
        time_left = max(0, self.deadline - self.elapsed)
        timeliness = time_left / self.deadline
        safety = max(0.0, 1.0 - self.safety_penalties)

        if 0 < self.baseline_time < 999999:
            efficiency = min(1.0, self.baseline_time / max(1, self.elapsed))
        else:
            efficiency = 0.5

        # Per-task scoring weights matching the design doc
        if self.task_name == "congestion_avoidance":
            score = 0.45 * timeliness + 0.15 * safety + 0.40 * efficiency
        elif self.task_name == "severe_weather_detour":
            score = 0.30 * timeliness + 0.50 * safety + 0.20 * efficiency
        elif self.task_name == "strategic_waiting":
            score = 0.40 * timeliness + 0.30 * safety + 0.30 * efficiency
        else:
            score = 0.50 * timeliness + 0.30 * safety + 0.20 * efficiency

        return round(max(0.0, min(1.0, score)), 4)

    def _apply_schedules(self):
        if not self.scenario:
            return

        for event in self.scenario.weather_schedule:
            if event.tick <= self.elapsed:
                self.weather_map[event.region] = event.condition

        for event in self.scenario.traffic_schedule:
            if event.tick <= self.elapsed < event.tick + event.duration:
                self.traffic_map[event.edge_key] = event.severity
            elif self.elapsed >= event.tick + event.duration:
                if self.traffic_map.get(event.edge_key) == event.severity:
                    self.traffic_map[event.edge_key] = "None"

    def _node_weather(self, node: str) -> str:
        region = NODE_TO_REGION.get(node, "inland")
        return self.weather_map.get(region, "Clear")

    def _get_node_weather_map(self) -> dict[str, str]:
        return {node: self._node_weather(node) for node in GRAPH_NODES}

    def _get_trend(self, node: str) -> str:
        if not self.scenario:
            return "stable"

        region = NODE_TO_REGION.get(node, "inland")
        current = self.weather_map.get(region, "Clear")
        current_idx = WEATHER_LEVELS.index(current)

        future_condition = current
        for event in self.scenario.weather_schedule:
            if self.elapsed < event.tick <= self.elapsed + 20 and event.region == region:
                future_condition = event.condition

        future_idx = WEATHER_LEVELS.index(future_condition)
        if future_idx < current_idx:
            return "improving"
        if future_idx > current_idx:
            return "worsening"
        return "stable"

    @property
    def state(self) -> State:
        return self._state
