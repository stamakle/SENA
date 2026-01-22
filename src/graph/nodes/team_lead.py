"""Team lead node for assigning specialist routes."""

from __future__ import annotations

from src.graph.state import GraphState, coerce_state, state_to_dict


def team_lead_node(state: GraphState | dict) -> dict:
    """Assign specialist routes based on query intent."""
    current = coerce_state(state)
    query = (current.augmented_query or current.query or "").lower()

    role_assignment = current.role_assignment or {}
    role_assignment["team_lead"] = "active"

    preferred_route = ""
    if any(term in query for term in ("root cause", "why", "analysis", "investigate")):
        preferred_route = "scientist"
    if any(term in query for term in ("correlate", "correlation", "pattern")):
        preferred_route = "correlation"
    if any(term in query for term in ("triage", "similar", "known issue", "history")):
        preferred_route = "triage"

    if preferred_route:
        role_assignment["preferred_route"] = preferred_route

    current.role_assignment = role_assignment
    current.route = "supervisor"
    return state_to_dict(current)
