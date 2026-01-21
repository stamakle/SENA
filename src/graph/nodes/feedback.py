"""Feedback node for prompt tuning logs."""

from __future__ import annotations

import json
from pathlib import Path

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict


def feedback_node(state: GraphState | dict) -> dict:
    """Summarize recent feedback logs."""

    current = coerce_state(state)
    cfg = load_config()
    path = Path(cfg.feedback_log_path)
    if not path.exists():
        current.response = "No feedback logs found."
        return state_to_dict(current)

    items = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    if not items:
        current.response = "Feedback log is empty."
        return state_to_dict(current)

    lines = [f"Feedback entries: {len(items)}", "Recent entries:"]
    for entry in items[-5:]:
        lines.append(
            f"- {entry.get('route', '')} | {entry.get('query', '')[:80]}"
        )
    current.response = "\n".join(lines)
    return state_to_dict(current)
