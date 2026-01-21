"""Memory node for session summaries and last live context."""

from __future__ import annotations

import os
from pathlib import Path

from src.agent.live_memory import get_live_entry
from src.agent.session_memory import get_summary
from src.graph.state import GraphState, coerce_state, state_to_dict


def _summary_path() -> Path:
    return Path(
        os.getenv(
            "SENA_SUMMARY_PATH",
            str(Path(__file__).resolve().parents[3] / "session_summaries.json"),
        )
    )


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def memory_node(state: GraphState | dict) -> dict:
    """Return stored session summary and last live metadata."""

    current = coerce_state(state)
    summary_entry = get_summary(_summary_path(), current.session_id) if current.session_id else None
    live_entry = get_live_entry(_live_path(), current.session_id) if current.session_id else None

    lines = ["Session memory:"]
    if summary_entry and summary_entry.get("summary"):
        lines.append("Summary:")
        lines.append(str(summary_entry.get("summary")))
    else:
        lines.append("Summary: not available yet.")

    if live_entry:
        host = str(live_entry.get("host", "")).strip()
        command = str(live_entry.get("command", "")).strip()
        lines.append("")
        lines.append("Last live command:")
        lines.append(f"- Host: {host or 'unknown'}")
        lines.append(f"- Command: {command or 'unknown'}")
    else:
        lines.append("")
        lines.append("Last live command: none")

    current.response = "\n".join(lines)
    return state_to_dict(current)
