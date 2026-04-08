"""Supply Chain Logistics Router — Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

try:
    from .models import RouteOption, RouterAction, RouterObservation
except ImportError:
    from models import RouteOption, RouterAction, RouterObservation


class RouterEnv(EnvClient[RouterAction, RouterObservation, State]):
    """
    Client for the Logistics Router environment.

    Connects via WebSocket to a running RouterEnvironment server.

    Usage:
        async with RouterEnv(base_url="http://localhost:8000") as client:
            result = await client.reset()
            print(result.observation.message)
            result = await client.step(RouterAction(action_type="move", target_node="B"))
    """

    def _step_payload(self, action: RouterAction) -> Dict:
        return {
            "action_type": action.action_type,
            "target_node": action.target_node,
            "wait_minutes": action.wait_minutes,
        }

    def _parse_result(self, payload: Dict) -> StepResult[RouterObservation]:
        obs_data = payload.get("observation", {})

        route_options = [
            RouteOption(**opt) for opt in obs_data.get("route_options", [])
        ]

        observation = RouterObservation(
            truck_location=obs_data.get("truck_location", ""),
            destination=obs_data.get("destination", ""),
            time_remaining_minutes=obs_data.get("time_remaining_minutes", 0),
            elapsed_minutes=obs_data.get("elapsed_minutes", 0),
            route_options=route_options,
            available_actions=obs_data.get("available_actions", []),
            last_action_summary=obs_data.get("last_action_summary", ""),
            last_action_error=obs_data.get("last_action_error", ""),
            alerts=obs_data.get("alerts", []),
            message=obs_data.get("message", ""),
            done=payload.get("done", False),
            reward=payload.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )
