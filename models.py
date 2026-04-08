"""
Data models for the Supply Chain Logistics Router Environment.

Defines the Action the LLM agent sends, the Observation it receives back,
and a helper RouteOption model describing each adjacent route.
"""

from typing import Optional

from openenv.core.env_server.types import Action, Observation
from pydantic import BaseModel, Field


class RouterAction(Action):
    """What the agent can do each turn: move to an adjacent node, or wait."""

    action_type: str = Field(..., description="'move' or 'wait'")
    target_node: str = Field(default="", description="Adjacent node ID (required for 'move')")
    wait_minutes: int = Field(default=10, description="10 or 20 (only used for 'wait')")


class RouteOption(BaseModel):
    """Describes one adjacent route visible to the agent."""

    to_node: str
    base_travel_time_minutes: int
    traffic_delay_minutes: int
    weather: str              # Clear, LightRain, HeavyRain, Storm
    risk_level: str           # Low, Medium, High, Blocked
    edge_status: str          # open, degraded, blocked
    eta_to_next_node: int     # base + traffic + weather penalty
    trend: str                # improving, stable, worsening


class RouterObservation(Observation):
    """
    What the agent sees after each step.

    The 'message' field is the LLM-readable natural language summary —
    this is what gets fed directly into the LLM prompt during inference.
    """

    truck_location: str = ""
    destination: str = ""
    time_remaining_minutes: int = 0
    elapsed_minutes: int = 0
    route_options: list[RouteOption] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    last_action_summary: str = ""
    last_action_error: str = ""
    alerts: list[str] = Field(default_factory=list)
    message: str = ""  # LLM-readable observation — the core interface to the agent
