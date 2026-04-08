"""
Task definitions and graders for the three scenario families.

Each grader takes final episode state and returns a score in [0.0, 1.0].
The graders use the same base formula (timeliness + safety + efficiency)
but weight components differently per task type.
"""

from graph import ALL_TASKS


def grade_episode(
    task_name: str,
    arrived: bool,
    elapsed: int,
    deadline: int,
    safety_penalties: float,
    baseline_time: int,
) -> float:
    """
    Compute graded score for a completed episode.
    Returns a float in [0.0, 1.0].
    """
    if not arrived:
        return 0.0

    timeliness = max(0.0, (deadline - elapsed) / deadline)
    safety = max(0.0, 1.0 - safety_penalties)
    efficiency = min(1.0, baseline_time / max(1, elapsed)) if baseline_time < 999999 else 0.5

    # Weight components based on what each task tests
    if task_name == "congestion_avoidance":
        # Emphasize timeliness and efficiency — weather is benign
        score = 0.45 * timeliness + 0.15 * safety + 0.40 * efficiency
    elif task_name == "severe_weather_detour":
        # Safety-first — did the agent avoid dangerous routes?
        score = 0.30 * timeliness + 0.50 * safety + 0.20 * efficiency
    elif task_name == "strategic_waiting":
        # Balanced — did the agent wait wisely and still arrive efficiently?
        score = 0.40 * timeliness + 0.30 * safety + 0.30 * efficiency
    else:
        # Default balanced weights
        score = 0.50 * timeliness + 0.30 * safety + 0.20 * efficiency

    return round(max(0.0, min(1.0, score)), 4)


TASKS = {
    name: {
        "description": template.description,
        "start": template.start_node,
        "destination": template.destination_node,
        "deadline": template.deadline_minutes,
    }
    for name, template in ALL_TASKS.items()
}
