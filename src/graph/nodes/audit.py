"""Audit node for post-run testcase log validation."""

from __future__ import annotations

from src.agent.audit_pipeline import run_audit_pipeline
from src.graph.state import GraphState, coerce_state, state_to_dict


def audit_node(state: GraphState | dict) -> dict:
    """Run audit pipeline for a testcase log path."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    current.response = run_audit_pipeline(query)
    return state_to_dict(current)
