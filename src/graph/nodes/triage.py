"""Historic Triage Node (Semantic Search of KB)."""

from __future__ import annotations
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.db.incident_store import search_incidents
from src.db.evidence_store import search_evidence

def triage_node(state: GraphState | dict) -> dict:
    """Analyze historical issues for triage."""
    current = coerce_state(state)
    query = current.query
    incident_hits = []
    evidence_hits = []
    try:
        incident_hits = search_incidents(query, limit=3)
    except Exception:
        incident_hits = []
    try:
        evidence_hits = search_evidence(query, limit=3, session_id=current.session_id)
    except Exception:
        evidence_hits = []

    lines = ["Historic Triage:"]
    if incident_hits:
        lines.append("Similar Incidents:")
        for incident in incident_hits:
            lines.append(
                f"- {incident.get('incident_id')}: {incident.get('title')} | Resolution: {incident.get('resolution')}"
            )
    if evidence_hits:
        lines.append("Recent Evidence Matches:")
        for ev in evidence_hits:
            signals = ev.get("signals") or {}
            signal_text = ", ".join(f"{k}={v}" for k, v in list(signals.items())[:5])
            lines.append(
                f"- {ev.get('host')} | {ev.get('source')} | {signal_text}"
            )
    if len(lines) == 1:
        lines.append("No similar incidents or evidence found. Consider collecting more logs.")
    current.response = "\n".join(lines)
    return state_to_dict(current)
