"""Incident Response Environment — client for connecting to the server."""

from typing import Dict

from openenv.core import EnvClient
from openenv.core.client_types import StepResult
from openenv.core.env_server.types import State

try:
    from .models import Alert, Finding, IncidentAction, IncidentObservation, ServiceStatus
except ImportError:
    from models import Alert, Finding, IncidentAction, IncidentObservation, ServiceStatus


class IncidentEnv(EnvClient[IncidentAction, IncidentObservation, State]):
    """
    Client for the Incident Response environment.

    Connects via WebSocket to a running IncidentEnvironment server.

    Usage:
        async with IncidentEnv(base_url="http://localhost:8000") as client:
            result = await client.reset()
            print(result.observation.message)
            result = await client.step(IncidentAction(
                action_type="investigate", target_service="payment-service"
            ))
    """

    def _step_payload(self, action: IncidentAction) -> Dict:
        return {
            "action_type": action.action_type,
            "target_service": action.target_service,
            "message_type": action.message_type,
            "escalation_target": action.escalation_target,
        }

    def _parse_result(self, payload: Dict) -> StepResult[IncidentObservation]:
        obs_data = payload.get("observation", {})

        active_alerts = [
            Alert(**a) for a in obs_data.get("active_alerts", [])
        ]
        findings = [
            Finding(**f) for f in obs_data.get("findings", [])
        ]
        visible_services = [
            ServiceStatus(**s) for s in obs_data.get("visible_services", [])
        ]

        observation = IncidentObservation(
            incident_id=obs_data.get("incident_id", ""),
            incident_summary=obs_data.get("incident_summary", ""),
            severity=obs_data.get("severity", "P3"),
            sla_remaining_minutes=obs_data.get("sla_remaining_minutes", 0),
            elapsed_minutes=obs_data.get("elapsed_minutes", 0),
            investigation_budget=obs_data.get("investigation_budget", 0.0),
            active_alerts=active_alerts,
            services_investigated=obs_data.get("services_investigated", []),
            findings=findings,
            visible_services=visible_services,
            mitigations_applied=obs_data.get("mitigations_applied", []),
            escalations_made=obs_data.get("escalations_made", []),
            communications_sent=obs_data.get("communications_sent", 0),
            last_action_summary=obs_data.get("last_action_summary", ""),
            last_action_error=obs_data.get("last_action_error", ""),
            available_actions=obs_data.get("available_actions", []),
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
