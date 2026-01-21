"""Feedback logging for prompt tuning and analysis."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def _truncate_text(text: str, max_len: int) -> str:
    """Return a truncated version of text for logging."""

    if not text or max_len <= 0:
        return text
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "...[truncated]"


def append_feedback_log(path_str: str, payload: Dict[str, Any]) -> None:
    """Append a feedback entry as JSONL."""

    if not path_str:
        return
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(payload)
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())
    if "response" in entry:
        entry["response"] = _truncate_text(str(entry["response"]), 2000)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
