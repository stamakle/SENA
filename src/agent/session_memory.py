"""Session summary storage helpers (Postgres-backed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.db.session_store import get_summary as _get_summary_db
from src.db.session_store import set_summary as _set_summary_db


# Step 3: Session summary storage.


def load_summaries(path: Path) -> Dict[str, Dict[str, Any]]:
    """Legacy API retained for compatibility (returns empty map)."""
    _ = path
    return {}


def save_summaries(path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    """Legacy API retained for compatibility."""
    _ = (path, data)


def get_summary(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the summary entry for a session, if present."""
    _ = path
    return _get_summary_db(session_id)


def set_summary(path: Path, session_id: str, summary: str, message_count: int) -> None:
    """Update the summary entry for a session."""
    _ = path
    _set_summary_db(session_id, summary, message_count)
