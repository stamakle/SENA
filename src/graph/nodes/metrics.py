"""Metrics node for displaying graph performance stats."""

from __future__ import annotations

from pathlib import Path

from src.agent.metrics import summarize_metrics
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict


def metrics_node(state: GraphState | dict) -> dict:
    """Return a short metrics summary."""

    current = coerce_state(state)
    cfg = load_config()
    metrics_path = Path(cfg.metrics_path)
    current.response = summarize_metrics(metrics_path)
    return state_to_dict(current)
