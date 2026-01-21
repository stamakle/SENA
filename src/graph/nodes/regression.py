"""Regression node for comparing testcase runs."""

from __future__ import annotations

import re
from pathlib import Path

from src.agent.regression_monitor import detect_regressions, format_regression_summary
from src.graph.state import GraphState, coerce_state, state_to_dict


def _extract_case_id(query: str) -> str:
    match = re.search(r"\b(?:TC|DSSTC)-\d+\b", query, re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _extract_host(query: str) -> str:
    match = re.search(r"(?:host|hostname|server|system)\s*[:#]?\s*([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bon\s+([\w.-]+)", query, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def regression_node(state: GraphState | dict) -> dict:
    """Compare recent testcase runs for regressions."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    case_id = _extract_case_id(query)
    host = _extract_host(query)
    status_path = Path(__file__).resolve().parents[3] / "data" / "exports" / "testcase_runs.json"

    if "all" in query.lower() and "regression" in query.lower():
        regressions = detect_regressions(status_path)
        if not regressions:
            current.response = "No regressions detected in recent runs."
            return state_to_dict(current)
        lines = ["Regressions detected:"]
        for entry in regressions:
            prev = entry.get("previous", {})
            curr = entry.get("current", {})
            lines.append(
                f"- {curr.get('case_id', '')} on {curr.get('host', '')}: "
                f"{prev.get('status', '')} -> {curr.get('status', '')}"
            )
        current.response = "\n".join(lines)
        return state_to_dict(current)

    current.response = format_regression_summary(status_path, case_id or None, host or None)
    return state_to_dict(current)
