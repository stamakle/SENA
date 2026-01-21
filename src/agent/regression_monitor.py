"""Regression monitor for testcase run history."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.agent.testcase_status import load_runs
from pathlib import Path


def _group_key(run: Dict[str, object]) -> Tuple[str, str]:
    return (str(run.get("case_id", "")).upper(), str(run.get("host", "")).lower())


def latest_two_runs(path: Path, case_id: Optional[str] = None, host: Optional[str] = None) -> List[Dict[str, object]]:
    """Return the latest two runs for a testcase/host filter."""

    runs = load_runs(path)
    if case_id:
        runs = [r for r in runs if str(r.get("case_id", "")).upper() == case_id.upper()]
    if host:
        runs = [r for r in runs if str(r.get("host", "")).lower() == host.lower()]
    if not runs:
        return []
    runs = sorted(runs, key=lambda r: r.get("started_at", ""))
    return runs[-2:]


def detect_regressions(path: Path) -> List[Dict[str, object]]:
    """Return runs where status regressed (pass -> fail)."""

    runs = load_runs(path)
    grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = {}
    for run in runs:
        grouped.setdefault(_group_key(run), []).append(run)
    regressions = []
    for group_runs in grouped.values():
        ordered = sorted(group_runs, key=lambda r: r.get("started_at", ""))
        if len(ordered) < 2:
            continue
        prev, latest = ordered[-2], ordered[-1]
        if str(prev.get("status", "")).lower() == "pass" and str(latest.get("status", "")).lower() == "fail":
            regressions.append({"previous": prev, "current": latest})
    return regressions


def format_regression_summary(path: Path, case_id: Optional[str], host: Optional[str]) -> str:
    """Format regression summary for a specific testcase/host."""

    latest = latest_two_runs(path, case_id=case_id, host=host)
    if not latest:
        return "No runs found to compare."
    if len(latest) == 1:
        run = latest[0]
        return (
            "Only one run found.\n"
            f"- Case: {run.get('case_id', '')}\n"
            f"- Host: {run.get('host', '')}\n"
            f"- Status: {run.get('status', '')}\n"
            f"- Started: {run.get('started_at', '')}"
        )
    prev, curr = latest[0], latest[1]
    return (
        "Latest run comparison:\n"
        f"- Previous: {prev.get('status', '')} at {prev.get('started_at', '')}\n"
        f"- Current: {curr.get('status', '')} at {curr.get('started_at', '')}\n"
        f"- Bundle: {curr.get('bundle_path', '')}"
    )
