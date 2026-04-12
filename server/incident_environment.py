"""
Incident Response Environment — core simulation engine.

Models an on-call SRE responding to a production incident.  Services
degrade over time via a deterministic schedule.  The agent investigates,
diagnoses root causes, applies fixes, communicates, and resolves.
"""

from __future__ import annotations

import copy
import os
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import Alert, Finding, IncidentAction, IncidentObservation, ServiceStatus
    from ..service_graph import (
        DEFAULT_HEALTHY_METRICS,
        SERVICES,
        SERVICE_NAMES,
        VALID_TEAMS,
        default_investigate_text,
        default_log_text,
        get_dependencies,
        get_dependents,
    )
    from ..scenarios import ALL_SCENARIOS, ScenarioTemplate
    from ..tasks import grade_episode
except ImportError:
    from models import Alert, Finding, IncidentAction, IncidentObservation, ServiceStatus
    from service_graph import (
        DEFAULT_HEALTHY_METRICS,
        SERVICES,
        SERVICE_NAMES,
        VALID_TEAMS,
        default_investigate_text,
        default_log_text,
        get_dependencies,
        get_dependents,
    )
    from scenarios import ALL_SCENARIOS, ScenarioTemplate
    from tasks import grade_episode


# ---------------------------------------------------------------------------
# Time cost of each action type (minutes)
# ---------------------------------------------------------------------------

ACTION_TIME: dict[str, int] = {
    "investigate": 2,
    "check_logs": 3,
    "check_metrics": 1,
    "restart": 5,
    "scale": 3,
    "rollback": 8,
    "escalate": 2,
    "communicate": 1,
    "resolve": 0,
}

VALID_ACTION_TYPES = set(ACTION_TIME.keys())
INVESTIGATE_ACTIONS = {"investigate", "check_logs", "check_metrics"}
REMEDIATION_ACTIONS = {"restart", "scale", "rollback"}
MAX_STEPS = 15


class IncidentEnvironment(Environment):
    SUPPORTS_CONCURRENT_SESSIONS: bool = False

    # ── constructor ──────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._state = State(episode_id=str(uuid4()), step_count=0)

        self.task_name: str = ""
        self.scenario: ScenarioTemplate | None = None
        self.elapsed: int = 0
        self.sla_deadline: int = 0
        self.budget: float = 0.0
        self.resolved: bool = False
        self.failed: bool = False

        # Service states (mutable copy per episode)
        self.service_states: dict[str, dict] = {}

        # Tracking
        self.services_investigated: list[str] = []
        self.findings: list[Finding] = []
        self.mitigations_applied: list[str] = []
        self.escalations_made: list[str] = []
        self.communications_sent: int = 0
        self.fixed_root_causes: set[str] = set()

        # Grading accumulators
        self.customer_impact: float = 0.0
        self.useful_actions: int = 0
        self.total_actions: int = 0

        # Action feedback
        self.last_action_summary: str = ""
        self.last_action_error: str = ""

    # ── reset ────────────────────────────────────────────────────────────

    def reset(
        self,
        seed: int | None = None,
        episode_id: str | None = None,
        task_name: str | None = None,
    ) -> IncidentObservation:
        resolved_task = task_name or os.environ.get(
            "TASK_NAME", "1_easy_payment_deploy"
        )

        self.scenario = copy.deepcopy(
            ALL_SCENARIOS.get(resolved_task, list(ALL_SCENARIOS.values())[0])
        )
        self.task_name = self.scenario.name

        self._state = State(
            episode_id=episode_id or str(uuid4()), step_count=0
        )
        self.elapsed = 0
        self.sla_deadline = self.scenario.sla_minutes
        self.budget = self.scenario.investigation_budget
        self.resolved = False
        self.failed = False

        # Build initial service states from defaults + scenario overrides
        self.service_states = {}
        for svc_name in SERVICE_NAMES:
            base = dict(DEFAULT_HEALTHY_METRICS[svc_name])
            if svc_name in self.scenario.initial_overrides:
                base.update(self.scenario.initial_overrides[svc_name])
            self.service_states[svc_name] = base

        self.services_investigated = []
        self.findings = []
        self.mitigations_applied = []
        self.escalations_made = []
        self.communications_sent = 0
        self.fixed_root_causes = set()

        self.customer_impact = 0.0
        self.useful_actions = 0
        self.total_actions = 0

        self.last_action_summary = "Incident opened — investigation started."
        self.last_action_error = ""

        return self._build_observation(reward=0.0, done=False)

    # ── step ─────────────────────────────────────────────────────────────

    def step(self, action: IncidentAction) -> IncidentObservation:
        self._state.step_count += 1

        if self.resolved or self.failed:
            return self._build_observation(reward=0.0, done=True)

        atype = action.action_type
        if atype not in VALID_ACTION_TYPES:
            self.last_action_error = (
                f"Unknown action type '{atype}'. "
                f"Valid: {sorted(VALID_ACTION_TYPES)}"
            )
            self.last_action_summary = self.last_action_error
            return self._build_observation(reward=0.0, done=False)

        # Advance time
        time_cost = ACTION_TIME[atype]
        self.elapsed += time_cost
        self.budget -= time_cost

        # Apply degradation schedule
        self._apply_degradation()

        # Accumulate customer impact (each minute a service is failing/down)
        self._accumulate_impact(time_cost)

        # Dispatch to handler
        handler = {
            "investigate": self._handle_investigate,
            "check_logs": self._handle_check_logs,
            "check_metrics": self._handle_check_metrics,
            "restart": self._handle_restart,
            "scale": self._handle_scale,
            "rollback": self._handle_rollback,
            "escalate": self._handle_escalate,
            "communicate": self._handle_communicate,
            "resolve": self._handle_resolve,
        }[atype]

        reward = handler(action)
        self.total_actions += 1

        # Check termination conditions
        done = self.resolved or self.failed
        if not done and self.elapsed >= self.sla_deadline:
            self.failed = True
            self.last_action_error = "SLA DEADLINE BREACHED — incident auto-closed."
            done = True
        if not done and self.budget <= 0:
            self.failed = True
            self.last_action_error = "Investigation budget exhausted."
            done = True
        if not done and self._state.step_count >= MAX_STEPS:
            self.failed = True
            self.last_action_error = "Maximum steps reached — incident auto-closed."
            done = True

        # If episode ended without explicit resolve, compute partial score
        if done and not self.resolved:
            reward = self._compute_final_score() * 0.5   # Penalty for not resolving

        return self._build_observation(reward=reward, done=done)

    # ── action handlers ──────────────────────────────────────────────────

    def _handle_investigate(self, action: IncidentAction) -> float:
        svc = action.target_service
        self.last_action_error = ""
        if svc not in SERVICES:
            self.last_action_error = (
                f"Unknown service '{svc}'. "
                f"Known services: {SERVICE_NAMES}"
            )
            self.last_action_summary = self.last_action_error
            return 0.0

        # Get investigation text — scenario-specific or default
        text = (
            self.scenario.investigate_content.get(svc)
            if self.scenario
            else None
        ) or default_investigate_text(svc)

        if svc not in self.services_investigated:
            self.services_investigated.append(svc)

        finding = Finding(
            source=svc,
            finding_type="investigation",
            summary=text.split("\n")[-1].replace("Status: ", ""),
        )
        self.findings.append(finding)

        self.last_action_summary = f"Investigated {svc}:\n{text}"
        return self._reward_for_investigation(svc, "investigate")

    def _handle_check_logs(self, action: IncidentAction) -> float:
        svc = action.target_service
        self.last_action_error = ""
        if svc not in SERVICES:
            self.last_action_error = f"Unknown service '{svc}'."
            self.last_action_summary = self.last_action_error
            return 0.0

        text = (
            self.scenario.log_content.get(svc)
            if self.scenario
            else None
        ) or default_log_text(svc)

        if svc not in self.services_investigated:
            self.services_investigated.append(svc)

        # Extract a finding from the logs
        lines = text.strip().split("\n")
        error_lines = [l for l in lines if "ERROR" in l or "WARN" in l]
        if error_lines:
            finding = Finding(
                source=svc,
                finding_type="log_analysis",
                summary=error_lines[0].strip(),
            )
            self.findings.append(finding)

        self.last_action_summary = f"Logs for {svc}:\n{text}"
        return self._reward_for_investigation(svc, "check_logs")

    def _handle_check_metrics(self, action: IncidentAction) -> float:
        svc = action.target_service
        self.last_action_error = ""
        if svc not in SERVICES:
            self.last_action_error = f"Unknown service '{svc}'."
            self.last_action_summary = self.last_action_error
            return 0.0

        state = self.service_states[svc]
        if svc not in self.services_investigated:
            self.services_investigated.append(svc)

        metric_text = (
            f"Metrics for {svc}:\n"
            f"  health: {state['health']}\n"
            f"  error_rate: {state['error_rate']:.3f}\n"
            f"  p99_latency_ms: {state['p99_latency_ms']}\n"
            f"  cpu_percent: {state['cpu_percent']:.1f}%\n"
            f"  memory_percent: {state['memory_percent']:.1f}%\n"
            f"  qps: {state['qps']}\n"
            f"  replicas: {state['replicas']}\n"
            f"  version: {state['version']}\n"
            f"  last_deploy: {state['last_deploy']}"
        )

        is_unhealthy = state["health"] != "healthy"
        if is_unhealthy:
            finding = Finding(
                source=svc,
                finding_type="metric_anomaly",
                summary=f"{svc}: error_rate={state['error_rate']:.3f}, "
                        f"p99={state['p99_latency_ms']}ms, "
                        f"cpu={state['cpu_percent']:.1f}%",
            )
            self.findings.append(finding)

        self.last_action_summary = metric_text
        return self._reward_for_investigation(svc, "check_metrics")

    def _handle_restart(self, action: IncidentAction) -> float:
        return self._apply_fix(action.target_service, "restart")

    def _handle_scale(self, action: IncidentAction) -> float:
        return self._apply_fix(action.target_service, "scale")

    def _handle_rollback(self, action: IncidentAction) -> float:
        return self._apply_fix(action.target_service, "rollback")

    def _apply_fix(self, svc: str, fix_type: str) -> float:
        self.last_action_error = ""
        if svc not in SERVICES:
            self.last_action_error = f"Unknown service '{svc}'."
            self.last_action_summary = self.last_action_error
            return 0.005

        state = self.service_states[svc]

        # Check if this service is a root cause with the matching fix
        if self.scenario:
            for rc in self.scenario.root_causes:
                if rc.service == svc and rc.fix == fix_type:
                    # CORRECT FIX
                    self.fixed_root_causes.add(svc)
                    state["health"] = "healthy"
                    state["error_rate"] = 0.002
                    state["p99_latency_ms"] = 45
                    state["cpu_percent"] = 25.0
                    if fix_type == "scale":
                        state["replicas"] = state["replicas"] * 3
                    self._recover_dependents(svc)
                    self.mitigations_applied.append(
                        f"{fix_type}({svc}) — EFFECTIVE"
                    )
                    self.last_action_summary = (
                        f"Applied {fix_type} to {svc} — service recovering. "
                        f"{rc.explanation}"
                    )
                    self.useful_actions += 1
                    return 0.15

                if rc.service == svc and rc.fix != fix_type:
                    # Right service, wrong fix
                    self.mitigations_applied.append(
                        f"{fix_type}({svc}) — INEFFECTIVE (wrong remediation)"
                    )
                    self.last_action_summary = (
                        f"Applied {fix_type} to {svc} — no improvement. "
                        f"The service may need a different remediation."
                    )
                    return 0.005

        # Not a root cause at all
        if state["health"] == "healthy":
            self.mitigations_applied.append(
                f"{fix_type}({svc}) — UNNECESSARY (service was healthy)"
            )
            self.last_action_summary = (
                f"Applied {fix_type} to {svc} — service was already healthy. "
                f"No effect."
            )
            return 0.005

        # Degraded service that's not a root cause — temporary improvement
        self.mitigations_applied.append(
            f"{fix_type}({svc}) — TEMPORARY (not root cause)"
        )
        self.last_action_summary = (
            f"Applied {fix_type} to {svc} — brief improvement but underlying "
            f"cause is elsewhere. Service will degrade again."
        )
        return 0.005

    def _handle_escalate(self, action: IncidentAction) -> float:
        self.last_action_error = ""
        team = action.escalation_target or action.target_service
        if team not in VALID_TEAMS:
            self.last_action_error = (
                f"Unknown team '{team}'. "
                f"Valid: {sorted(VALID_TEAMS)}"
            )
            self.last_action_summary = self.last_action_error
            return 0.0

        if team not in self.escalations_made:
            self.escalations_made.append(team)

        self.last_action_summary = (
            f"Escalated to {team}. They have been paged and are joining "
            f"the incident channel."
        )
        return 0.02

    def _handle_communicate(self, action: IncidentAction) -> float:
        self.last_action_error = ""
        self.communications_sent += 1
        msg_type = action.message_type or "update"

        self.last_action_summary = (
            f"Status update posted ({msg_type}): Stakeholders notified. "
            f"Total communications: {self.communications_sent}."
        )
        return 0.03 if self.communications_sent <= 3 else 0.01

    def _handle_resolve(self, _action: IncidentAction) -> float:
        self.last_action_error = ""
        self.resolved = True
        score = self._compute_final_score()
        self.last_action_summary = (
            f"Incident marked as resolved. Final score: {score:.3f}"
        )
        return score

    # ── helpers ───────────────────────────────────────────────────────────

    def _reward_for_investigation(self, svc: str, action: str) -> float:
        """Return per-step reward for an investigation action."""
        if not self.scenario:
            return 0.01

        root_cause_names = {rc.service for rc in self.scenario.root_causes}

        # Investigating a root cause service
        if svc in root_cause_names:
            self.useful_actions += 1
            if action == "check_logs":
                return 0.05   # Logs are where the clues are
            return 0.04

        # Investigating a service that depends on or is depended on by a root cause
        related = set()
        for rc_name in root_cause_names:
            related.update(get_dependents(rc_name))
            related.update(get_dependencies(rc_name))
        if svc in related:
            self.useful_actions += 1
            return 0.03

        # Investigating an unrelated service — not wasted, but less useful
        return 0.01

    def _apply_degradation(self) -> None:
        """Apply any scheduled degradation events up to current elapsed time."""
        if not self.scenario:
            return
        for event in self.scenario.degradation_schedule:
            if event.tick > self.elapsed:
                continue
            # Skip if the root cause for this event is already fixed
            if event.caused_by and event.caused_by in self.fixed_root_causes:
                continue
            state = self.service_states.get(event.service)
            if not state:
                continue
            state["health"] = event.health
            if event.error_rate is not None:
                state["error_rate"] = event.error_rate
            if event.p99_latency_ms is not None:
                state["p99_latency_ms"] = event.p99_latency_ms
            if event.cpu_percent is not None:
                state["cpu_percent"] = event.cpu_percent

    def _recover_dependents(self, fixed_service: str) -> None:
        """After a root cause is fixed, recover services that depended on it."""
        for event in (self.scenario.degradation_schedule if self.scenario else []):
            if event.caused_by != fixed_service:
                continue
            svc = event.service
            state = self.service_states.get(svc)
            if not state:
                continue
            # Restore to defaults
            defaults = DEFAULT_HEALTHY_METRICS[svc]
            state["health"] = defaults["health"]
            state["error_rate"] = defaults["error_rate"]
            state["p99_latency_ms"] = defaults["p99_latency_ms"]
            state["cpu_percent"] = defaults["cpu_percent"]

    def _accumulate_impact(self, minutes: int) -> None:
        """Accumulate customer impact based on how many services are unhealthy."""
        impact_per_min = 0.0
        for svc_name, state in self.service_states.items():
            svc_node = SERVICES.get(svc_name)
            if not svc_node:
                continue
            crit_weight = {"critical": 3.0, "high": 1.5, "medium": 0.5}.get(
                svc_node.criticality, 0.5
            )
            health_weight = {
                "healthy": 0.0, "degraded": 0.3, "failing": 0.7, "down": 1.0
            }.get(state["health"], 0.0)
            impact_per_min += crit_weight * health_weight * 0.002
        self.customer_impact += impact_per_min * minutes

    def _compute_final_score(self) -> float:
        return grade_episode(
            self.task_name,
            resolved=self.resolved,
            root_causes_fixed=len(self.fixed_root_causes),
            total_root_causes=len(self.scenario.root_causes) if self.scenario else 1,
            elapsed=self.elapsed,
            sla_deadline=self.sla_deadline,
            customer_impact=self.customer_impact,
            useful_actions=self.useful_actions,
            total_actions=max(1, self.total_actions),
            communications_sent=self.communications_sent,
        )

    # ── observation builder ──────────────────────────────────────────────

    def _build_observation(self, reward: float, done: bool) -> IncidentObservation:
        alerts = []
        if self.scenario:
            for a in self.scenario.alerts:
                alerts.append(Alert(**a))

        # Build visible service list (only investigated services)
        visible = []
        for svc_name in self.services_investigated:
            state = self.service_states.get(svc_name)
            if state:
                visible.append(ServiceStatus(name=svc_name, **state))

        message = self._render_message(alerts)

        return IncidentObservation(
            incident_id=self._state.episode_id,
            incident_summary=self.scenario.incident_summary if self.scenario else "",
            severity=self.scenario.severity if self.scenario else "P3",
            sla_remaining_minutes=max(0, self.sla_deadline - self.elapsed),
            elapsed_minutes=self.elapsed,
            investigation_budget=round(max(0, self.budget), 1),
            active_alerts=alerts,
            services_investigated=list(self.services_investigated),
            findings=list(self.findings),
            visible_services=visible,
            mitigations_applied=list(self.mitigations_applied),
            escalations_made=list(self.escalations_made),
            communications_sent=self.communications_sent,
            last_action_summary=self.last_action_summary,
            last_action_error=self.last_action_error,
            available_actions=sorted(VALID_ACTION_TYPES),
            message=message,
            done=done,
            reward=round(max(0.0, min(1.0, reward)), 4),
            metadata={
                "task_name": self.task_name,
                "sla_minutes": self.sla_deadline,
                "root_causes_fixed": len(self.fixed_root_causes),
                "total_root_causes": (
                    len(self.scenario.root_causes) if self.scenario else 0
                ),
            },
        )

    def _render_message(self, alerts: list[Alert]) -> str:
        lines: list[str] = []

        # Header
        lines.append(
            f"=== INCIDENT RESPONSE: {self._state.episode_id[:12]} ==="
        )
        lines.append(
            f"Severity: {self.scenario.severity if self.scenario else 'P3'} | "
            f"SLA: {max(0, self.sla_deadline - self.elapsed)} min remaining | "
            f"Elapsed: {self.elapsed} min | "
            f"Budget: {max(0, self.budget):.0f} min"
        )
        lines.append("")

        # Incident summary
        if self.scenario:
            lines.append(f"Incident: {self.scenario.incident_summary}")
            lines.append("")

        # Alerts
        lines.append("--- ACTIVE ALERTS ---")
        severity_icon = {"CRITICAL": "🔴", "WARNING": "🟡", "INFO": "ℹ️"}
        for alert in alerts:
            icon = severity_icon.get(alert.severity, "•")
            lines.append(
                f"  {icon} {alert.severity}: {alert.service} — {alert.message}"
            )
        lines.append("")

        # Findings
        if self.findings:
            lines.append(f"--- FINDINGS ({len(self.findings)} discovered) ---")
            for i, f in enumerate(self.findings[-8:], 1):
                lines.append(f"  {i}. [{f.finding_type}] {f.source}: {f.summary}")
            lines.append("")

        # Services investigated
        if self.services_investigated:
            lines.append(
                f"--- SERVICES INVESTIGATED: "
                f"{', '.join(self.services_investigated)} ---"
            )
        else:
            lines.append("--- SERVICES INVESTIGATED: none yet ---")

        # Mitigations
        if self.mitigations_applied:
            lines.append(f"--- MITIGATIONS APPLIED ---")
            for m in self.mitigations_applied:
                lines.append(f"  • {m}")
        else:
            lines.append("--- MITIGATIONS APPLIED: none ---")
        lines.append("")

        lines.append(f"--- COMMUNICATIONS: {self.communications_sent} sent ---")
        lines.append("")

        # Available actions
        lines.append("--- AVAILABLE ACTIONS ---")
        lines.append(
            "  investigate(<service>), check_logs(<service>), "
            "check_metrics(<service>)"
        )
        lines.append(
            "  restart(<service>), rollback(<service>), scale(<service>)"
        )
        lines.append(
            "  escalate(<team>), communicate(<type>), resolve"
        )
        lines.append("")
        lines.append(
            f"Known services: {', '.join(SERVICE_NAMES)}"
        )
        lines.append(
            f"Known teams: {', '.join(sorted(VALID_TEAMS))}"
        )
        lines.append("")

        # Last action
        lines.append(f"Last action: {self.last_action_summary}")
        if self.last_action_error:
            lines.append(f"⚠ ERROR: {self.last_action_error}")

        return "\n".join(lines)

    # ── state property ───────────────────────────────────────────────────

    @property
    def state(self) -> State:
        return self._state
