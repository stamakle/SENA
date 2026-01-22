"""Manager node for role-based orchestration."""

from __future__ import annotations

from src.graph.state import GraphState, coerce_state, state_to_dict


def manager_node(state: GraphState | dict) -> dict:
    """Assign roles and route complex tasks to team lead."""
    current = coerce_state(state)
    query = (current.augmented_query or current.query or "").lower()

    role_assignment = current.role_assignment or {}
    role_assignment["manager"] = "active"

    complex_signals = [
        "root cause",
        "why did",
        "analyze",
        "investigate",
        "correlate",
        "triage",
        "fix",
        "mitigation",
        "multiple",
        "compare",
    ]
    is_complex = any(term in query for term in complex_signals) or len(query.split()) > 20
    if is_complex:
        role_assignment["team_lead"] = "active"
        current.route = "team_lead"
    else:
        current.route = "supervisor"

    current.role_assignment = role_assignment
    return state_to_dict(current)
