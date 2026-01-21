"""Correlation Node."""

from __future__ import annotations
import re
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.analysis.correlation import find_fleet_correlations

def correlation_node(state: GraphState | dict) -> dict:
    """Analyze fleet-wide correlations for an issue."""
    current = coerce_state(state)
    query = current.query
    cfg = load_config()

    match = re.search(r"\b(?:host|hostname)\s+([\w.-]+)", query, re.IGNORECASE)
    host = match.group(1) if match else None

    if host:
        results = find_fleet_correlations(cfg.pg_dsn, "generic_error", host)
        current.response = "Correlation Analysis:\n" + "\n".join(results)
    else:
        current.response = "No specific host found in query to correlate."

    return state_to_dict(current)
