# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.

"""
Data models for the Logistics Router Environment.
"""

from typing import Literal, Optional
from openenv.core.env_server.types import Action, Observation
from pydantic import Field

class LogisticsAction(Action):
    """Action for the Logistics environment - move to a node or wait."""
    
    action_type: Literal["MOVE", "WAIT"] = Field(
        ..., 
        description="Must be either 'MOVE' to travel to an adjacent node, or 'WAIT' to stay put."
    )
    target_node: Optional[str] = Field(
        default=None, 
        description="The ID of the node to move to. Required if action_type is 'MOVE'."
    )
    wait_time_mins: Optional[int] = Field(
        default=None, 
        description="Minutes to wait. Required if action_type is 'WAIT'."
    )

class LogisticsObservation(Observation):
    """Observation from the Logistics environment - primarily a text string for the LLM."""
    
    llm_prompt: str = Field(
        default="", 
        description="The formatted text observation describing location, weather, traffic, and choices."
    )
    current_node: str = Field(
        default="", 
        description="The ID of the node the truck is currently at."
    )
    time_elapsed_mins: int = Field(
        default=0, 
        description="Total minutes elapsed since the route started."
    )