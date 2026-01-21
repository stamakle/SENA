"""Testcase run status storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_runs(path: Path) -> List[Dict[str, object]]:
    """Load the run list from disk."""

    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_runs(path: Path, runs: List[Dict[str, object]]) -> None:
    """Persist run list to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs, indent=2), encoding="utf-8")


def append_run(path: Path, entry: Dict[str, object]) -> None:
    """Append a new run entry."""

    runs = load_runs(path)
    runs.append(entry)
    save_runs(path, runs)


def update_run(path: Path, run_id: str, updates: Dict[str, object]) -> None:
    """Update a run entry by run_id."""

    runs = load_runs(path)
    for run in runs:
        if str(run.get("run_id")) == run_id:
            run.update(updates)
            run["updated_at"] = _now()
            break
    save_runs(path, runs)


def latest_run(
    path: Path,
    case_id: Optional[str] = None,
    host: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[Dict[str, object]]:
    """Return the latest run that matches the filters."""

    runs = load_runs(path)
    if not runs:
        return None

    def _match(run: Dict[str, object]) -> bool:
        if case_id and str(run.get("case_id", "")).upper() != case_id.upper():
            return False
        if host and str(run.get("host", "")).lower() != host.lower():
            return False
        if session_id and str(run.get("session_id", "")) != session_id:
            return False
        return True

    filtered = [run for run in runs if _match(run)]
    if not filtered:
        return None
    return sorted(filtered, key=lambda r: r.get("started_at", ""))[-1]


def format_status(run: Dict[str, object]) -> str:
    """Format a run entry for user display."""

    return "\n".join(
        [
            f"Testcase: {run.get('case_id', '')}",
            f"Host: {run.get('host', '')}",
            f"Status: {run.get('status', '')}",
            f"Started: {run.get('started_at', '')}",
            f"Ended: {run.get('ended_at', '')}",
            f"Log dir: {run.get('log_dir', '')}",
            f"Bundle: {run.get('bundle_path', '')}",
        ]
    )
