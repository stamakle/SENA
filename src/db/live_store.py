"""Live output storage helpers backed by Postgres."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.config import load_config
from src.db.postgres import get_connection, _jsonb
from src.db.session_store import ensure_session


def get_live_entry(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the stored live entry for a session."""
    if not session_id:
        return None
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT output, summary, truncated, host, command, output_mode,
                       sudo_ok, sudo_message, strict_mode, auto_execute, pending, proposed
                FROM live_outputs
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        keys = [
            "output",
            "summary",
            "truncated",
            "host",
            "command",
            "output_mode",
            "sudo_ok",
            "sudo_message",
            "strict_mode",
            "auto_execute",
            "pending",
            "proposed",
        ]
        return dict(zip(keys, row))
    finally:
        if conn is not None:
            conn.close()


def _upsert_live_entry(session_id: str, payload: Dict[str, Any]) -> None:
    """Upsert live output row."""
    ensure_session(session_id)
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO live_outputs (
                    session_id, output, summary, truncated, host, command,
                    output_mode, sudo_ok, sudo_message, strict_mode, auto_execute,
                    pending, proposed, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (session_id) DO UPDATE SET
                    output = EXCLUDED.output,
                    summary = EXCLUDED.summary,
                    truncated = EXCLUDED.truncated,
                    host = EXCLUDED.host,
                    command = EXCLUDED.command,
                    output_mode = EXCLUDED.output_mode,
                    sudo_ok = EXCLUDED.sudo_ok,
                    sudo_message = EXCLUDED.sudo_message,
                    strict_mode = EXCLUDED.strict_mode,
                    auto_execute = EXCLUDED.auto_execute,
                    pending = EXCLUDED.pending,
                    proposed = EXCLUDED.proposed,
                    updated_at = now()
                """,
                (
                    session_id,
                    payload.get("output", ""),
                    payload.get("summary", ""),
                    payload.get("truncated", False),
                    payload.get("host", ""),
                    payload.get("command", ""),
                    payload.get("output_mode", ""),
                    payload.get("sudo_ok"),
                    payload.get("sudo_message", ""),
                    payload.get("strict_mode"),
                    payload.get("auto_execute"),
                    payload.get("pending", False),
                    _jsonb(payload.get("proposed")) if payload.get("proposed") is not None else None,
                ),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def set_live_entry(
    session_id: str,
    output: str,
    summary: str = "",
    max_chars: int = 0,
    host: str = "",
    command: str = "",
    output_mode: str = "",
) -> None:
    """Store the latest live output and summary."""
    if not session_id:
        return
    trimmed_output = output or ""
    truncated = False
    if max_chars and len(trimmed_output) > max_chars:
        trimmed_output = trimmed_output[:max_chars].rstrip() + "\n...[truncated]"
        truncated = True

    existing = get_live_entry(session_id) or {}
    payload = {
        "output": trimmed_output,
        "summary": summary or existing.get("summary", ""),
        "truncated": truncated,
        "host": host or existing.get("host", ""),
        "command": command or existing.get("command", ""),
        "output_mode": output_mode or existing.get("output_mode", ""),
        "sudo_ok": existing.get("sudo_ok"),
        "sudo_message": existing.get("sudo_message", ""),
        "strict_mode": existing.get("strict_mode"),
        "auto_execute": existing.get("auto_execute"),
        "pending": False,
        "proposed": existing.get("proposed"),
    }
    _upsert_live_entry(session_id, payload)


def clear_live_entry(session_id: str) -> None:
    """Remove stored live output for a session."""
    if not session_id:
        return
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM live_outputs WHERE session_id = %s", (session_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def set_live_status(session_id: str, sudo_ok: bool, message: str = "") -> None:
    """Store sudo check status for a session."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {
        "output": existing.get("output", ""),
        "summary": existing.get("summary", ""),
        "truncated": existing.get("truncated", False),
        "host": existing.get("host", ""),
        "command": existing.get("command", ""),
        "output_mode": existing.get("output_mode", ""),
        "sudo_ok": sudo_ok,
        "sudo_message": message or "",
        "strict_mode": existing.get("strict_mode"),
        "auto_execute": existing.get("auto_execute"),
        "pending": existing.get("pending", False),
        "proposed": existing.get("proposed"),
    }
    _upsert_live_entry(session_id, payload)


def set_live_strict_mode(session_id: str, strict_mode: bool) -> None:
    """Store strict mode preference for a session."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {**existing, "strict_mode": strict_mode}
    _upsert_live_entry(session_id, payload)


def set_live_auto_execute(session_id: str, auto_execute: bool) -> None:
    """Store auto-execute preference for a session."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {**existing, "auto_execute": auto_execute}
    _upsert_live_entry(session_id, payload)


def set_live_pending(session_id: str, host: str, command: str) -> None:
    """Store a pending live command for confirmation."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {**existing, "host": host, "command": command, "pending": True}
    _upsert_live_entry(session_id, payload)


def set_live_proposed(session_id: str, name: str, command: str, source_query: str) -> None:
    """Store a proposed custom command for approval."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {**existing, "proposed": {"name": name, "command": command, "source_query": source_query}}
    _upsert_live_entry(session_id, payload)


def clear_live_proposed(session_id: str) -> None:
    """Clear proposed command for approval."""
    if not session_id:
        return
    existing = get_live_entry(session_id) or {}
    payload = {**existing, "proposed": None}
    _upsert_live_entry(session_id, payload)
