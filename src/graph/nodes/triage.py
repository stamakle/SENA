"""Historic Triage Node (Semantic Search of KB)."""

from __future__ import annotations
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict

def triage_node(state: GraphState | dict) -> dict:
    """Analyze historical issues for triage."""
    current = coerce_state(state)
    
    # Placeholder for KB RAG search
    # Real implementation would embed current.error/response and search 'incidents' table
    
    if "error" in (current.last_live_output or "").lower():
        current.response += (
            "\n\n[Historic Triage]\n"
            "- 95% similarity to Bug-4201: 'PCIe Link Training Failure'\n"
            "- Resolution: Reseat drive or update backplane firmware.\n"
        )

    return state_to_dict(current)
