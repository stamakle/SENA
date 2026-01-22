"""Session storage for live (SSH) outputs and summaries (Postgres-backed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from src.db.live_store import (
    get_live_entry as _get_live_entry_db,
    set_live_entry as _set_live_entry_db,
    clear_live_entry as _clear_live_entry_db,
    set_live_status as _set_live_status_db,
    set_live_strict_mode as _set_live_strict_mode_db,
    set_live_auto_execute as _set_live_auto_execute_db,
    set_live_pending as _set_live_pending_db,
    set_live_proposed as _set_live_proposed_db,
    clear_live_proposed as _clear_live_proposed_db,
)


# Step 15: Live-RAG session memory.


def _load_data(path: Path) -> Dict[str, Dict[str, Any]]:
    """Legacy API retained for compatibility."""
    _ = path
    return {}


def _save_data(path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    """Legacy API retained for compatibility."""
    _ = (path, data)


def get_live_entry(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the stored live entry for a session."""
    _ = path
    return _get_live_entry_db(session_id)


def set_live_entry(
    path: Path,
    session_id: str,
    output: str,
    summary: str = "",
    max_chars: int = 0,
    host: str = "",
    command: str = "",
    output_mode: str = "",
) -> None:
    """Store the latest live output and summary."""
    _ = path
    _set_live_entry_db(
        session_id,
        output,
        summary=summary,
        max_chars=max_chars,
        host=host,
        command=command,
        output_mode=output_mode,
    )


def clear_live_entry(path: Path, session_id: str) -> None:
    """Remove stored live output for a session."""
    _ = path
    _clear_live_entry_db(session_id)


def set_live_status(path: Path, session_id: str, sudo_ok: bool, message: str = "") -> None:
    """Store sudo check status for a session."""
    _ = path
    _set_live_status_db(session_id, sudo_ok, message=message)


def set_live_strict_mode(path: Path, session_id: str, strict_mode: bool) -> None:
    """Store strict mode preference for a session."""
    _ = path
    _set_live_strict_mode_db(session_id, strict_mode)


def set_live_auto_execute(path: Path, session_id: str, auto_execute: bool) -> None:
    """Store auto-execute preference for a session."""
    _ = path
    _set_live_auto_execute_db(session_id, auto_execute)


def set_live_pending(path: Path, session_id: str, host: str, command: str) -> None:
    """Store a pending live command for confirmation."""
    _ = path
    _set_live_pending_db(session_id, host, command)


def set_live_proposed(path: Path, session_id: str, name: str, command: str, source_query: str) -> None:
    """Store a proposed custom command for approval."""
    _ = path
    _set_live_proposed_db(session_id, name, command, source_query)


def get_live_proposed(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the proposed command for approval."""
    _ = path
    entry = _get_live_entry_db(session_id) or {}
    return entry.get("proposed") if entry else None


def clear_live_proposed(path: Path, session_id: str) -> None:
    """Clear proposed command for approval."""
    _ = path
    _clear_live_proposed_db(session_id)
