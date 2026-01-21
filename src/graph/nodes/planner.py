"""Planner node for high-level SSD validation tasks."""

from __future__ import annotations

from src.graph.state import GraphState, coerce_state, state_to_dict


def planner_node(state: GraphState | dict) -> dict:
    """Return a simple plan outline for the requested task."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    cleaned = query
    if cleaned.lower().startswith("/plan"):
        cleaned = cleaned[len("/plan") :].strip()
    current.response = (
        "Proposed plan:\n\n"
        f"- Clarify scope and target systems for: {cleaned or 'SSD validation task'}\n"
        "- Gather relevant test cases and recent logs\n"
        "- Run required live checks (lspci, nvme list, dmesg)\n"
        "- Validate results against expected outcomes\n"
        "- Summarize findings and next actions"
    )
    return state_to_dict(current)
