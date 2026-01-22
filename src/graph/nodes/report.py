"""Report node for summarizing SSD validation results."""

from __future__ import annotations

from src.agent.live_memory import get_live_entry
from src.db.evidence_store import load_recent_evidence
from src.agent.testcase_status import latest_run
from src.graph.nodes.orchestrator import STATUS_PATH
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
    """Return a concise report based on available artifacts."""

    current = coerce_state(state)
    live_output = ""
    if current.session_id:
        entry = get_live_entry(_live_path(), current.session_id)
        if entry:
            live_output = str(entry.get("output", "")).strip()
    status = "insufficient data"
    if live_output or current.context:
        status = "data captured"
    evidence_lines = []
    if current.session_id:
        try:
            evidence = load_recent_evidence(current.session_id, limit=5)
        except Exception:
            evidence = []
        for ev in evidence:
            signals = ev.get("signals") or {}
            evidence_lines.append(
                f"- {ev.get('host')} | {ev.get('source')} | "
                + ", ".join(f"{k}={v}" for k, v in list(signals.items())[:5])
            )
    latest = latest_run(STATUS_PATH, session_id=current.session_id) if current.session_id else None
    run_line = ""
    if latest:
        run_line = f"- Latest testcase: {latest.get('case_id')} on {latest.get('host')} (status: {latest.get('status')})"
    current.response = (
        "Report draft:\n"
        f"- Status: {status}\n"
        f"{run_line}\n"
        "- Evidence summary:\n"
        + ("\n".join(evidence_lines) if evidence_lines else "- (none captured)")
        + "\n- Next: specify expected results to finalize pass/fail"
    )
    return state_to_dict(current)
