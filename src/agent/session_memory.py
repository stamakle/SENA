"""Session summary storage helpers.

This module stores per-session summaries on disk for follow-up questions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


# Step 3: Session summary storage.


def load_summaries(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load summary data from disk."""

    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def save_summaries(path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    """Persist summaries to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def get_summary(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the summary entry for a session, if present."""

    data = load_summaries(path)
    return data.get(session_id)


def set_summary(path: Path, session_id: str, summary: str, message_count: int) -> None:
    """Update the summary entry for a session."""

    data = load_summaries(path)
    data[session_id] = {
        "summary": summary,
        "message_count": message_count,
    }
    save_summaries(path, data)
