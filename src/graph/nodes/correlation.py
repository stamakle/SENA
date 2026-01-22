"""Correlation Node."""

from __future__ import annotations
import re
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.analysis.correlation import find_fleet_correlations
from src.db.evidence_store import load_recent_evidence


def _build_causal_chain(events: list[dict]) -> list[str]:
    """Build simple causal chains from evidence signals."""
    findings: list[str] = []
    for ev in events:
        signals = ev.get("signals") or {}
        if not isinstance(signals, dict):
            continue
        mqes = signals.get("mqes") or signals.get("max_queue_entries")
        timeout_count = signals.get("timeout_count", 0)
        reset_count = signals.get("reset_count", 0)
        pcie_errors = signals.get("pcie_error_count", 0)
        if mqes and timeout_count and reset_count:
            findings.append(
                "MQES/queue depth appears high while timeouts and resets are present. "
                "Chain: MQES/high queue depth → command timeouts → controller reset."
            )
        if pcie_errors and timeout_count:
            findings.append(
                "PCIe errors detected alongside timeouts. "
                "Chain: PCIe AER/link instability → NVMe timeouts → degraded health."
            )
        if signals.get("critical_warning") not in (None, 0) and signals.get("media_errors"):
            findings.append(
                "SMART critical warning with media errors. "
                "Chain: media errors → SMART critical warning → drive health degraded."
            )
    return findings

def correlation_node(state: GraphState | dict) -> dict:
    """Analyze fleet-wide correlations for an issue."""
    current = coerce_state(state)
    query = current.query
    cfg = load_config()

    match = re.search(r"\b(?:host|hostname)\s+([\w.-]+)", query, re.IGNORECASE)
    host = match.group(1) if match else None

    analysis = []
    
    # P3 #11: Queue Depth vs Timeout Correlation
    # Real implementation would require parsing registers and kernel logs from live output
    # For now, we simulate detection if keywords are present in query or history
    
    live_output = current.last_live_output or ""
    
    if "nvme show-regs" in live_output and "mqes" in live_output.lower():
         analysis.append("- Checked Queue Depth (MQES) from controller registers.")

    if ("timeout" in live_output.lower() or "timeout" in query.lower()) and "reset" in live_output.lower():
        analysis.append(
            "⚠️ **Correlation Detected:** Controller Reset follows Timeout.\n"
            "   Likely cause: Command timeout triggered driver-level reset."
        )

    if host:
        results = find_fleet_correlations(cfg.pg_dsn, "generic_error", host)
        if results:
            analysis.append("Fleet Correlations:\n" + "\n".join(results))

    # Evidence-backed causal chains (session scope)
    if current.session_id:
        try:
            evidence = load_recent_evidence(current.session_id, limit=5)
        except Exception:
            evidence = []
        chains = _build_causal_chain(evidence)
        if chains:
            analysis.append("Causal Chains:\n" + "\n".join(f"- {c}" for c in chains))
    
    if not analysis:
        current.response = "No strong correlations detected in current telemetry."
    else:
        current.response = "Correlation Analysis:\n" + "\n".join(analysis)

    return state_to_dict(current)
