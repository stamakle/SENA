"""Session storage helpers backed by Postgres."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from src.config import load_config
from src.db.postgres import get_connection, _jsonb


def ensure_session(session_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """Ensure a session row exists and update timestamp."""
    if not session_id:
        return
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (session_id, metadata, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (session_id) DO UPDATE
                SET updated_at = now(),
                    metadata = COALESCE(EXCLUDED.metadata, sessions.metadata)
                """,
                (session_id, _jsonb(metadata) if metadata else None),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def touch_session(session_id: str) -> None:
    """Update session updated_at timestamp."""
    if not session_id:
        return
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute("UPDATE sessions SET updated_at = now() WHERE session_id = %s", (session_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def append_message(session_id: str, role: str, content: str) -> None:
    """Append a session message."""
    if not session_id or not content:
        return
    ensure_session(session_id)
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_messages (session_id, role, content, created_at)
                VALUES (%s, %s, %s, now())
                """,
                (session_id, role, content),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def load_messages(session_id: str, limit: int = 50) -> List[Dict[str, str]]:
    """Load recent messages for a session."""
    if not session_id:
        return []
    cfg = load_config()
    conn = None
    messages: List[Dict[str, str]] = []
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM session_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        for role, content in reversed(rows):
            messages.append({"role": role, "content": content})
    finally:
        if conn is not None:
            conn.close()
    return messages


def set_summary(session_id: str, summary: str, message_count: int) -> None:
    """Persist a session summary."""
    if not session_id:
        return
    ensure_session(session_id)
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session_summaries (session_id, summary, message_count, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (session_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    message_count = EXCLUDED.message_count,
                    updated_at = now()
                """,
                (session_id, summary, int(message_count)),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def get_summary(session_id: str) -> Optional[Dict[str, Any]]:
    """Return summary entry for a session."""
    if not session_id:
        return None
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT summary, message_count
                FROM session_summaries
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {"summary": row[0], "message_count": int(row[1] or 0)}
    finally:
        if conn is not None:
            conn.close()


def get_latest_session_id() -> Optional[str]:
    """Return the most recently updated session ID."""
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC NULLS LAST LIMIT 1"
            )
            row = cur.fetchone()
        return row[0] if row else None
    finally:
        if conn is not None:
            conn.close()


def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """List recent sessions by update time."""
    cfg = load_config()
    conn = None
    sessions: List[Dict[str, Any]] = []
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT session_id, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        for session_id, updated_at in rows:
            sessions.append({"session_id": session_id, "updated_at": updated_at})
    finally:
        if conn is not None:
            conn.close()
    return sessions


def delete_session(session_id: str) -> None:
    """Delete a session and its messages."""
    if not session_id:
        return
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE session_id = %s", (session_id,))
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def delete_all_sessions() -> None:
    """Delete all sessions."""
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions")
        conn.commit()
    finally:
        if conn is not None:
            conn.close()
