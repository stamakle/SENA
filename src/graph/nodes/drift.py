"""Drift Analysis Node for detecting subtle numeric shifts."""

from __future__ import annotations
from src.graph.state import GraphState, coerce_state, state_to_dict

def drift_node(state: GraphState | dict) -> dict:
    """Analyze if numerical metrics have drifted from baseline."""
    current = coerce_state(state)
    
    # Placeholder logic for drift analysis
    # In a real implementation, this would fetch historical metrics from TimeScaleDB/Prometheus
    
    if "temperature" in current.query.lower():
        current.response = (
            "Drift Analysis:\n"
            "- Current Avg Temp: 45C\n"
            "- Baseline (30-day): 38C\n"
            "- Drift: +18% (Warning threshold is +10%)\n"
            "Recommendation: Check airflow or fan speeds."
        )
    else:
        current.response = "No drift detected in generic metrics."

    return state_to_dict(current)
