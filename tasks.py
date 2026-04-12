"""
Grading logic for the Incident Response Environment.

Each episode is scored on five weighted components. The weights shift
per task to emphasise different skills at each difficulty level.
"""

from __future__ import annotations

from scenarios import ALL_SCENARIOS


# ---------------------------------------------------------------------------
# Grading formula
# ---------------------------------------------------------------------------

# (root_cause_accuracy, timeliness, impact, efficiency, communication)
TASK_WEIGHTS: dict[str, tuple[float, ...]] = {
    "1_easy_payment_deploy":     (0.30, 0.30, 0.15, 0.15, 0.10),
    "2_medium_db_conn_leak":     (0.25, 0.20, 0.25, 0.20, 0.10),
    "3_hard_dual_failure":       (0.20, 0.15, 0.25, 0.25, 0.15),
    "4_frontier_cache_corruption": (0.15, 0.10, 0.30, 0.30, 0.15),
}


def grade_episode(
    task_name: str,
    *,
    resolved: bool,
    root_causes_fixed: int,
    total_root_causes: int,
    elapsed: int,
    sla_deadline: int,
    customer_impact: float,
    useful_actions: int,
    total_actions: int,
    communications_sent: int,
) -> float:
    """Return a score in [0.01, 0.99] for a completed episode."""

    if not resolved and root_causes_fixed == 0:
        return 0.01

    # 1. Root cause accuracy — did you fix the right thing(s)?
    root_acc = root_causes_fixed / max(1, total_root_causes)

    # 2. Timeliness — how much SLA slack remained?
    if resolved and elapsed < sla_deadline:
        timeliness = max(0.0, (sla_deadline - elapsed) / sla_deadline)
    else:
        timeliness = 0.0

    # 3. Customer impact — lower is better (accumulated damage)
    impact_score = max(0.0, 1.0 - customer_impact)

    # 4. Investigation efficiency — useful vs wasted steps
    if total_actions > 0:
        efficiency = min(1.0, useful_actions / total_actions)
    else:
        efficiency = 0.0

    # 5. Communication — at least 2 updates for full marks
    comm = min(1.0, communications_sent * 0.5)

    # Weighted sum
    w = TASK_WEIGHTS.get(task_name, (0.20, 0.20, 0.20, 0.20, 0.20))
    score = (
        w[0] * root_acc
        + w[1] * timeliness
        + w[2] * impact_score
        + w[3] * efficiency
        + w[4] * comm
    )

    return round(max(0.01, min(0.99, score)), 4)


# ---------------------------------------------------------------------------
# Task registry (for /tasks endpoint and inference)
# ---------------------------------------------------------------------------

TASKS: dict[str, dict] = {
    name: {
        "description": scenario.description,
        "difficulty": scenario.difficulty,
        "severity": scenario.severity,
        "sla_minutes": scenario.sla_minutes,
    }
    for name, scenario in ALL_SCENARIOS.items()
}