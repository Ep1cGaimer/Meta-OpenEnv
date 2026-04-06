# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.

"""Logistics Router Environment Client."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

try:
    from .models import LogisticsAction, LogisticsObservation
except ImportError:
    from models import LogisticsAction, LogisticsObservation


class LogisticsClient(EnvClient[LogisticsAction, LogisticsObservation, State]):
    """
    Client for the Logistics Router Environment.
    Maintains a persistent connection to the environment server to pipe 
    LLM actions and return stochastic observations.
    """

    def _step_payload(self, action: LogisticsAction) -> Dict:
        """
        Convert LogisticsAction to JSON payload for the step message.
        """
        return {
            "action_type": action.action_type,
            "target_node": action.target_node,
            "wait_time_mins": action.wait_time_mins,
        }

    def _parse_result(self, payload: Dict) -> StepResult[LogisticsObservation]:
        """
        Parse server response into StepResult[LogisticsObservation].
        """
        obs_data = payload.get("observation", {})
        
        observation = LogisticsObservation(
            llm_prompt=obs_data.get("llm_prompt", ""),
            current_node=obs_data.get("current_node", ""),
            time_elapsed_mins=obs_data.get("time_elapsed_mins", 0),
            done=payload.get("done", False),
            reward=payload.get("reward", 0.0),
            metadata=obs_data.get("metadata", {}),
        )

        return StepResult(
            observation=observation,
            reward=payload.get("reward", 0.0),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict) -> State:
        """
        Parse server response into State object.
        """
        return State(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
        )