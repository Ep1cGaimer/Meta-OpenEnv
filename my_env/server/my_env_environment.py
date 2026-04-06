# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.

"""
Logistics Router Environment Implementation.
"""

from uuid import uuid4
import random
import networkx as nx

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import LogisticsAction, LogisticsObservation
except ImportError:
    from models import LogisticsAction, LogisticsObservation


class LogisticsEnvironment(Environment):
    """
    A stochastic graph-based POMDP logistics simulator using NetworkX.
    Generates a new scalable 'hub-and-spoke' map every episode.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    WEATHER_STATES = ["Clear", "Light Rain", "Heavy Rain", "Thunderstorm"]

    def __init__(self, num_nodes: int = 20):
        """Initialize the logistics environment."""
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self.num_nodes = num_nodes  # Scale this up as needed for bigger graphs
        self.current_node = None
        self.goal_node = None
        self.time_elapsed = 0
        self.graph = nx.Graph()
        self.node_weather = {}

    def _generate_random_graph(self):
        """Generates a hub-and-spoke logistics network using NetworkX."""
        # Barabási-Albert model creates realistic hub-and-spoke logistics networks.
        # It guarantees the graph is connected so a path always exists.
        m_edges = 2 if self.num_nodes > 2 else 1
        raw_graph = nx.barabasi_albert_graph(n=self.num_nodes, m=m_edges)
        
        # Relabel nodes to strings (e.g., "0", "1", "2") for clean LLM outputs
        self.graph = nx.relabel_nodes(raw_graph, {i: str(i) for i in raw_graph.nodes()})

        # Assign base travel times to all edges
        for u, v in self.graph.edges():
            self.graph[u][v]["base_time"] = random.randint(30, 120)
            self.graph[u][v]["traffic_mult"] = 1.0

    def _update_stochastic_engine(self):
        """Rerolls weather for nodes and updates traffic multipliers on edges."""
        # Update weather for all nodes
        for node in self.graph.nodes():
            self.node_weather[node] = random.choices(
                self.WEATHER_STATES, weights=[60, 20, 15, 5], k=1
            )[0]

        # Update traffic multipliers based on weather at the edge's endpoints
        for u, v in self.graph.edges():
            # Traffic is influenced by the worst weather of the two connecting nodes
            w_u = self.node_weather[u]
            w_v = self.node_weather[v]
            
            penalty_u = self.WEATHER_STATES.index(w_u) * 0.3
            penalty_v = self.WEATHER_STATES.index(w_v) * 0.3
            max_weather_penalty = max(penalty_u, penalty_v)
            
            base_mult = random.uniform(0.8, 1.5)
            self.graph[u][v]["traffic_mult"] = round(base_mult + max_weather_penalty, 2)

    def _generate_llm_observation_text(self) -> str:
        """Parses the local NetworkX graph state into a text prompt for the LLM."""
        local_weather = self.node_weather[self.current_node]
        
        prompt = (
            f"OBSERVATION: You are currently at Hub {self.current_node}. "
            f"Your destination is Hub {self.goal_node}. "
            f"Total time elapsed: {self.time_elapsed} minutes. "
            f"Local weather is '{local_weather}'.\n\n"
            f"Available adjacent routes:\n"
        )

        # Use NetworkX neighbors to find adjacent nodes dynamically
        for adj_node in self.graph.neighbors(self.current_node):
            adj_weather = self.node_weather[adj_node]
            edge_data = self.graph[self.current_node][adj_node]
            est_time = int(edge_data["base_time"] * edge_data["traffic_mult"])
            prompt += f"- Move to Hub {adj_node}: Est. travel time {est_time} mins. Destination weather: '{adj_weather}'.\n"

        prompt += "\nYou can also choose to WAIT to let weather/traffic shift."
        return prompt

    def reset(self) -> LogisticsObservation:
        """Reset the environment for a new episode."""
        self._state = State(episode_id=str(uuid4()), step_count=0)
        
        self._generate_random_graph()
        self._update_stochastic_engine()
        
        # Start at node "0", goal is the very last node in the network
        self.current_node = "0"
        self.goal_node = str(self.num_nodes - 1)
        self.time_elapsed = 0

        return LogisticsObservation(
            llm_prompt=self._generate_llm_observation_text(),
            current_node=self.current_node,
            time_elapsed_mins=self.time_elapsed,
            done=False,
            reward=0.0,
        )

    def step(self, action: LogisticsAction) -> LogisticsObservation:
        """Execute the LLM's action, advance time, roll stochasticity, return state."""
        self._state.step_count += 1
        
        step_reward = 0.0
        done = False

        if action.action_type == "MOVE":
            target = action.target_node
            
            # Check if edge exists using NetworkX
            if self.graph.has_edge(self.current_node, target):
                # Access edge attributes easily via NetworkX graph indexing
                edge_data = self.graph[self.current_node][target]
                travel_time = int(edge_data["base_time"] * edge_data["traffic_mult"])
                
                self.time_elapsed += travel_time
                self.current_node = target
                
                # Penalize time taken (-0.1 per minute)
                step_reward -= (travel_time * 0.1)
                
                # Penalize driving into bad weather
                if self.node_weather[target] == "Thunderstorm":
                    step_reward -= 20.0
                elif self.node_weather[target] == "Heavy Rain":
                    step_reward -= 10.0
            else:
                # Invalid move penalty
                step_reward -= 50.0

        elif action.action_type == "WAIT":
            wait_time = action.wait_time_mins if action.wait_time_mins else 60
            self.time_elapsed += wait_time
            step_reward -= (wait_time * 0.05)
            
        else:
            step_reward -= 10.0

        # Check termination condition
        if self.current_node == self.goal_node:
            done = True
            step_reward += 500.0  # Massive success bonus
            
        # Reroll the world if not done
        if not done:
            self._update_stochastic_engine()

        return LogisticsObservation(
            llm_prompt=self._generate_llm_observation_text(),
            current_node=self.current_node,
            time_elapsed_mins=self.time_elapsed,
            done=done,
            reward=step_reward,
            metadata={"step": self._state.step_count}
        )

    @property
    def state(self) -> State:
        return self._state