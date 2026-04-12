"""
Data models for the Incident Response Environment.

Defines the Action the LLM agent sends, the Observation it receives back,
and helper models for service status, findings, and alerts.
"""

from typing import Optional

from openenv.core.env_server.types import Action, Observation
from pydantic import BaseModel, Field


class IncidentAction(Action):
    """What the agent can do each turn.

    action_type choices:
        investigate     — Get overview of a service (team, deploys, deps)
        check_logs      — Read recent log lines for a service
        check_metrics   — Query live metrics for a service
        restart         — Restart a service
        scale           — Scale up a service's replicas
        rollback        — Roll back a service to the previous version
        escalate        — Escalate to a specialist team
        communicate     — Post a stakeholder status update
        resolve         — Declare the incident resolved (terminal)
    """

    action_type: str = Field(
        ...,
        description=(
            "'investigate', 'check_logs', 'check_metrics', "
            "'restart', 'scale', 'rollback', "
            "'escalate', 'communicate', 'resolve'"
        ),
    )
    target_service: str = Field(
        default="",
        description="Service to act on (required for investigate/check_logs/check_metrics/restart/scale/rollback)",
    )
    message_type: str = Field(
        default="investigating",
        description="For communicate: 'investigating', 'update', 'mitigated', 'resolved'",
    )
    escalation_target: str = Field(
        default="",
        description="For escalate: 'database-team', 'platform-team', 'commerce-team', 'security-team'",
    )


class Alert(BaseModel):
    """An active alert fired by the monitoring system."""

    severity: str   # CRITICAL, WARNING, INFO
    service: str
    message: str


class Finding(BaseModel):
    """A piece of evidence the agent discovered during investigation."""

    source: str         # Service or action that produced this
    finding_type: str   # log_analysis, metric_anomaly, deploy_correlation, dependency_issue
    summary: str        # Human-readable summary


class ServiceStatus(BaseModel):
    """Observable status of a single service."""

    name: str
    health: str             # healthy, degraded, failing, down
    error_rate: float
    p99_latency_ms: int
    cpu_percent: float
    memory_percent: float
    qps: int
    replicas: int
    last_deploy: str        # e.g. "12 minutes ago"
    version: str


class IncidentObservation(Observation):
    """What the agent sees after each step.

    The 'message' field is the natural-language summary fed directly
    into the LLM prompt during inference.
    """

    # Incident context
    incident_id: str = ""
    incident_summary: str = ""
    severity: str = ""          # P1, P2, P3

    # Time
    sla_remaining_minutes: int = 0
    elapsed_minutes: int = 0
    investigation_budget: float = 0.0

    # Alerts
    active_alerts: list[Alert] = Field(default_factory=list)

    # Discovered information
    services_investigated: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    visible_services: list[ServiceStatus] = Field(default_factory=list)

    # Actions taken
    mitigations_applied: list[str] = Field(default_factory=list)
    escalations_made: list[str] = Field(default_factory=list)
    communications_sent: int = 0

    # Action feedback
    last_action_summary: str = ""
    last_action_error: str = ""
    available_actions: list[str] = Field(default_factory=list)

    # LLM-readable observation
    message: str = ""
