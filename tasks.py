"""
Task definitions and graders for the four scenario families.

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
        return 0.01

    timeliness = max(0.0, (deadline - elapsed) / deadline)
    safety = max(0.0, 1.0 - safety_penalties)
    efficiency = min(1.0, baseline_time / max(1, elapsed)) if baseline_time < 999999 else 0.5

    # Weight components based on what each task tests
    if task_name == "1_easy_clear_path":
        score = 0.50 * timeliness + 0.20 * safety + 0.30 * efficiency
    elif task_name == "2_medium_congestion":
        score = 0.40 * timeliness + 0.20 * safety + 0.40 * efficiency
    elif task_name == "3_hard_strategic_wait":
        score = 0.30 * timeliness + 0.30 * safety + 0.40 * efficiency
    elif task_name == "4_frontier_greedy_trap":
        score = 0.20 * timeliness + 0.50 * safety + 0.30 * efficiency
    else:
        # Default balanced weights
        score = 0.50 * timeliness + 0.30 * safety + 0.20 * efficiency

    return round(max(0.01, min(0.99, score)), 4)


TASKS = {
    name: {
        "description": template.description,
        "start": template.start_node,
        "destination": template.destination_node,
        "deadline": template.deadline_minutes,
    }
    for name, template in ALL_TASKS.items()
}