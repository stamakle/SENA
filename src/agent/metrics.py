"""Metrics logging and summaries for graph runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def append_metric(path: Path, entry: Dict[str, object]) -> None:
    """Append a single metric entry to a JSONL file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def load_metrics(path: Path, limit: int = 500) -> List[Dict[str, object]]:
    """Load recent metric entries."""

    if not path.exists():
        return []
    items: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    if limit and len(items) > limit:
        return items[-limit:]
    return items


def summarize_metrics(path: Path, limit: int = 500) -> str:
    """Return a short metrics summary."""

    items = load_metrics(path, limit=limit)
    if not items:
        return "No metrics logged yet."

    durations = [float(item.get("duration_ms", 0)) for item in items if item.get("duration_ms") is not None]
    avg_duration = sum(durations) / max(len(durations), 1)
    route_counts: Dict[str, int] = {}
    for item in items:
        route = str(item.get("route", "unknown"))
        route_counts[route] = route_counts.get(route, 0) + 1

    top_routes = sorted(route_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = [
        f"Total runs: {len(items)}",
        f"Average duration: {avg_duration:.1f} ms",
        "Top routes:",
    ]
    lines.extend([f"- {route}: {count}" for route, count in top_routes])
    return "\n".join(lines)
