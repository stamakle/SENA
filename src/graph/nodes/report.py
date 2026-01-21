"""Report node for summarizing SSD validation results."""

from __future__ import annotations

from src.agent.live_memory import get_live_entry
from src.graph.state import GraphState, coerce_state, state_to_dict
from pathlib import Path
import os


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def report_node(state: GraphState | dict) -> dict:
    """Return a concise report stub based on available artifacts."""

    current = coerce_state(state)
    live_output = ""
    if current.session_id:
        entry = get_live_entry(_live_path(), current.session_id)
        if entry:
            live_output = str(entry.get("output", "")).strip()
    status = "insufficient data"
    if live_output or current.context:
        status = "data captured"
    current.response = (
        "Report draft:\n"
        f"- Status: {status}\n"
        "- Evidence: live logs and/or RAG context\n"
        "- Next: specify expected results to finalize pass/fail"
    )
    return state_to_dict(current)
