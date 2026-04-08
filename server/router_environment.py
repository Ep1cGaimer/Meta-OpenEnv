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
        WEATHER_LEVELS,
        TRAFFIC_PENALTY,
        ScenarioTemplate,
        compute_edge_eta,
        compute_edge_fuel,
        dijkstra_shortest_time,
        get_risk_level,
        is_edge_blocked,
        generate_graph,
    )
except ImportError:
    from models import RouteOption, RouterAction, RouterObservation
    from graph import (
        WEATHER_LEVELS,
        TRAFFIC_PENALTY,
        ScenarioTemplate,
        compute_edge_eta,
        compute_edge_fuel,
        dijkstra_shortest_time,
        get_risk_level,
        is_edge_blocked,
        generate_graph,
    )


class RouterEnvironment(Environment):
    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)

        self.current_node = ""
        self.destination = ""
        self.deadline = 0
        self.elapsed = 0
        self.fuel = 0.0
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
        
        # Dynamic Graph Properties
        self.graph_nodes = []
        self.adjacency = {}
        self.node_to_region = {}

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        task_name: str | None = None,
    ) -> RouterObservation:
        resolved_task_name = task_name or os.environ.get(
            "TASK_NAME", "1_easy_clear_path"
        )
        resolved_seed = (
            seed if seed is not None else int(os.environ.get("EPISODE_SEED", "42"))
        )

        self.rng = random.Random(resolved_seed)
        
        # 1. Dynamically Generate the 25-node grid for this specific seed!
        (self.graph_nodes, self.adjacency, self.node_to_region, 
         _, all_tasks) = generate_graph(resolved_seed)

        # 2. Fetch the base hard-coded template
        base_scenario = all_tasks.get(resolved_task_name, list(all_tasks.values())[0])

        # 3. CRITICAL: Deep copy the scenario so we don't mutate the global templates!
        self.scenario = copy.deepcopy(base_scenario)
        self.task_name = self.scenario.name

        # 4. Jitter weather
        for event in self.scenario.weather_schedule:
            jitter = self.rng.randint(-10, 10)
            event.tick = max(0, event.tick + jitter) 

        # 5. Jitter traffic
        for event in self.scenario.traffic_schedule:
            start_jitter = self.rng.randint(-5, 15)
            duration_jitter = self.rng.randint(-20, 20)
            event.tick = max(0, event.tick + start_jitter)
            if event.duration < 900: 
                event.duration = max(10, event.duration + duration_jitter)

        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        self.current_node = self.scenario.start_node
        self.destination = self.scenario.destination_node
        self.deadline = self.scenario.deadline_minutes
        self.fuel = self.scenario.initial_fuel
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
            self.current_node, self.destination, self.graph_nodes, self.adjacency, node_weather, self.traffic_map
        )

        clear_weather = {node: "Clear" for node in self.graph_nodes}
        baseline_clear = dijkstra_shortest_time(
            self.current_node, self.destination, self.graph_nodes, self.adjacency, clear_weather, {}
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
        edges = self.adjacency.get(self.current_node, [])
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
        fuel_cost = compute_edge_fuel(edge, target_weather, traffic)
        
        self.elapsed += travel_time
        self.fuel -= fuel_cost
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
            f"Burned {fuel_cost} Fuel. Weather: {target_weather}, Traffic: {traffic}."
        )

        if self.fuel <= 0:
            self.failed = True
            self.last_action_error = "CRITICAL FAILURE: OUT OF FUEL."
            return self._build_observation(reward=0.0, done=True)

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
        fuel_cost = 0.1 * minutes
        self.fuel -= fuel_cost
        
        self._apply_schedules()
        self.last_action_summary = f"Waited {minutes} min at {self.current_node}. Burned {fuel_cost} Fuel (Idling)."

        if self.fuel <= 0:
            self.failed = True
            self.last_action_error = "CRITICAL FAILURE: OUT OF FUEL."
            return self._build_observation(reward=0.0, done=True)

        if self.elapsed >= self.deadline:
            self.failed = True
            return self._build_observation(reward=0.0, done=True)

        step_reward = max(
            0.0, min(0.05, (self.deadline - self.elapsed) / self.deadline * 0.05)
        )
        return self._build_observation(reward=step_reward, done=False)

    def _node_grid_pos(self, node: str) -> tuple[int, int]:
        """Return (row, col) for a node on the 4x4 grid."""
        idx = int(node[1:])
        return idx // 4, idx % 4

    def _manhattan_distance(self, node_a: str, node_b: str) -> int:
        """Manhattan distance between two nodes on the grid."""
        r1, c1 = self._node_grid_pos(node_a)
        r2, c2 = self._node_grid_pos(node_b)
        return abs(r1 - r2) + abs(c1 - c2)

    def _build_observation(self, reward: float, done: bool) -> RouterObservation:
        route_options = []
        action_list = []
        alerts: list[str] = []
        current_dist = self._manhattan_distance(self.current_node, self.destination)

        for edge in self.adjacency.get(self.current_node, []):
            weather = self._node_weather(edge.to_node)
            traffic = self.traffic_map.get(f"{edge.from_node}->{edge.to_node}", "None")
            blocked = is_edge_blocked(edge, weather)
            risk = get_risk_level(edge, weather, traffic)
            eta = compute_edge_eta(edge, weather, traffic) if not blocked else 9999
            fuel_est = compute_edge_fuel(edge, weather, traffic) if not blocked else 9999
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
                    fuel_cost_estimate=fuel_est,
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
        message = self._render_message(route_options, alerts, current_dist)

        return RouterObservation(
            truck_location=self.current_node,
            destination=self.destination,
            time_remaining_minutes=max(0, self.deadline - self.elapsed),
            elapsed_minutes=self.elapsed,
            fuel_remaining=round(self.fuel, 2),
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
                "baseline_fuel": getattr(self.scenario, 'initial_fuel', 0.0),
            },
        )

    def _render_message(self, routes: list[RouteOption], alerts: list[str], current_dist: int) -> str:
        """Render the observation message with task-dependent information levels.

        Easy:     Full coords + CLOSER/farther hints + distance count
        Medium:   Grid coords only (no CLOSER, no distance) — agent computes direction
        Hard:     Grid coords only + must reason about weather trends
        Frontier: Grid coords only + storm trap requires counter-intuitive planning
        """
        cur_r, cur_c = self._node_grid_pos(self.current_node)
        dst_r, dst_c = self._node_grid_pos(self.destination)

        # --- Header: always show coords, but distance only for easy ---
        if self.task_name == "1_easy_clear_path":
            lines = [
                f"Truck at {self.current_node} (row {cur_r}, col {cur_c}). Destination: {self.destination} (row {dst_r}, col {dst_c}).",
                f"Distance to destination: {current_dist} hops.",
                f"Time remaining: {max(0, self.deadline - self.elapsed)} min. | Fuel: {round(max(0, self.fuel), 1)} liters",
                "",
                "Route options:",
            ]
        else:
            # Medium, Hard, Frontier: coords shown, no distance count
            lines = [
                f"Truck at {self.current_node} (row {cur_r}, col {cur_c}). Destination: {self.destination} (row {dst_r}, col {dst_c}).",
                f"Time remaining: {max(0, self.deadline - self.elapsed)} min. | Fuel: {round(max(0, self.fuel), 1)} liters",
                "",
                "Route options:",
            ]

        # --- Route options: CLOSER hint only for easy ---
        for index, route in enumerate(routes, 1):
            nr, nc = self._node_grid_pos(route.to_node)

            # Build direction label (Easy only)
            if self.task_name == "1_easy_clear_path":
                next_dist = self._manhattan_distance(route.to_node, self.destination)
                if next_dist < current_dist:
                    direction = ", CLOSER to destination"
                elif next_dist > current_dist:
                    direction = ", farther from destination"
                else:
                    direction = ", same distance"
            else:
                direction = ""  # No directional hint for Medium/Hard/Frontier

            coord_label = f"row {nr}, col {nc}{direction}"

            if route.edge_status == "blocked":
                lines.append(
                    f"  {index}. {self.current_node}->{route.to_node} ({coord_label}) | "
                    f"BLOCKED ({route.weather})"
                )
            else:
                delay = (
                    f" (+{route.traffic_delay_minutes} min traffic)"
                    if route.traffic_delay_minutes
                    else ""
                )
                lines.append(
                    f"  {index}. {self.current_node}->{route.to_node} ({coord_label}) | "
                    f"ETA {route.eta_to_next_node} min{delay} | "
                    f"Fuel {route.fuel_cost_estimate} | "
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
        if self.fuel <= 0:
            return 0.01
            
        time_left = max(0, self.deadline - self.elapsed)
        timeliness = time_left / self.deadline
        safety = max(0.0, 1.0 - self.safety_penalties)

        if 0 < self.baseline_time < 999999:
            efficiency = min(1.0, self.baseline_time / max(1, self.elapsed))
        else:
            efficiency = 0.5

        if self.task_name == "1_easy_clear_path":
            score = 0.50 * timeliness + 0.20 * safety + 0.30 * efficiency
        elif self.task_name == "2_medium_congestion":
            score = 0.40 * timeliness + 0.20 * safety + 0.40 * efficiency
        elif self.task_name == "3_hard_strategic_wait":
            score = 0.30 * timeliness + 0.30 * safety + 0.40 * efficiency
        elif self.task_name == "4_frontier_greedy_trap":
            score = 0.20 * timeliness + 0.50 * safety + 0.30 * efficiency
        else:
            score = 0.50 * timeliness + 0.30 * safety + 0.20 * efficiency

        return round(max(0.01, min(0.99, score)), 4)

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
        region = self.node_to_region.get(node, "inland")
        return self.weather_map.get(region, "Clear")

    def _get_node_weather_map(self) -> dict[str, str]:
        return {node: self._node_weather(node) for node in self.graph_nodes}

    def _get_trend(self, node: str) -> str:
        if not self.scenario:
            return "stable"

        region = self.node_to_region.get(node, "inland")
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