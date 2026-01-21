"""Session storage for live (SSH) outputs and summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


# Step 15: Live-RAG session memory.


def _load_data(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load live session data from disk."""

    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _save_data(path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    """Persist live session data to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def get_live_entry(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the stored live entry for a session."""

    data = _load_data(path)
    return data.get(session_id)


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

    trimmed_output = output
    truncated = False
    if max_chars and len(trimmed_output) > max_chars:
        trimmed_output = trimmed_output[:max_chars].rstrip() + "\n...[truncated]"
        truncated = True

    data = _load_data(path)
    prior = data.get(session_id, {})
    data[session_id] = {
        "output": trimmed_output,
        "summary": summary,
        "truncated": truncated,
        "sudo_ok": prior.get("sudo_ok"),
        "sudo_message": prior.get("sudo_message", ""),
        "strict_mode": prior.get("strict_mode"),
        "auto_execute": prior.get("auto_execute"),
        "output_mode": output_mode or prior.get("output_mode", ""),
        "host": host or prior.get("host", ""),
        "command": command or prior.get("command", ""),
        "proposed": prior.get("proposed"),
        "pending": False,
    }
    _save_data(path, data)


def clear_live_entry(path: Path, session_id: str) -> None:
    """Remove stored live output for a session."""

    data = _load_data(path)
    if session_id in data:
        del data[session_id]
        _save_data(path, data)


def set_live_status(path: Path, session_id: str, sudo_ok: bool, message: str = "") -> None:
    """Store sudo check status for a session."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    entry["sudo_ok"] = sudo_ok
    entry["sudo_message"] = message
    entry.setdefault("output", "")
    entry.setdefault("summary", "")
    entry.setdefault("truncated", False)
    entry.setdefault("strict_mode", None)
    entry.setdefault("auto_execute", None)
    entry.setdefault("pending", False)
    data[session_id] = entry
    _save_data(path, data)


def set_live_strict_mode(path: Path, session_id: str, strict_mode: bool) -> None:
    """Store strict mode preference for a session."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    entry["strict_mode"] = strict_mode
    entry.setdefault("output", "")
    entry.setdefault("summary", "")
    entry.setdefault("truncated", False)
    entry.setdefault("sudo_ok", None)
    entry.setdefault("sudo_message", "")
    entry.setdefault("auto_execute", None)
    entry.setdefault("pending", False)
    data[session_id] = entry
    _save_data(path, data)


def set_live_auto_execute(path: Path, session_id: str, auto_execute: bool) -> None:
    """Store auto-execute preference for a session."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    entry["auto_execute"] = auto_execute
    entry.setdefault("output", "")
    entry.setdefault("summary", "")
    entry.setdefault("truncated", False)
    entry.setdefault("sudo_ok", None)
    entry.setdefault("sudo_message", "")
    entry.setdefault("strict_mode", None)
    entry.setdefault("pending", False)
    data[session_id] = entry
    _save_data(path, data)


def set_live_pending(path: Path, session_id: str, host: str, command: str) -> None:
    """Store a pending live command for confirmation."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    entry["host"] = host
    entry["command"] = command
    entry["pending"] = True
    entry.setdefault("output", "")
    entry.setdefault("summary", "")
    entry.setdefault("truncated", False)
    entry.setdefault("sudo_ok", None)
    entry.setdefault("sudo_message", "")
    entry.setdefault("strict_mode", None)
    entry.setdefault("auto_execute", None)
    entry.setdefault("proposed", None)
    data[session_id] = entry
    _save_data(path, data)


def set_live_proposed(path: Path, session_id: str, name: str, command: str, source_query: str) -> None:
    """Store a proposed custom command for approval."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    entry["proposed"] = {
        "name": name,
        "command": command,
        "source_query": source_query,
    }
    entry.setdefault("output", "")
    entry.setdefault("summary", "")
    entry.setdefault("truncated", False)
    entry.setdefault("sudo_ok", None)
    entry.setdefault("sudo_message", "")
    entry.setdefault("strict_mode", None)
    entry.setdefault("auto_execute", None)
    entry.setdefault("pending", False)
    data[session_id] = entry
    _save_data(path, data)


def get_live_proposed(path: Path, session_id: str) -> Dict[str, Any] | None:
    """Return the proposed command for approval."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    return entry.get("proposed") if entry else None


def clear_live_proposed(path: Path, session_id: str) -> None:
    """Clear proposed command for approval."""

    data = _load_data(path)
    entry = data.get(session_id, {})
    if entry and "proposed" in entry:
        entry["proposed"] = None
        data[session_id] = entry
        _save_data(path, data)
