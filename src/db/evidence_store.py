"""Evidence event storage and retrieval helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.config import load_config
from src.db.postgres import get_connection, _jsonb, _vector_literal
from src.llm.ollama_client import embed_text


def _build_evidence_text(source: str, signals: Dict[str, Any], raw_excerpt: str) -> str:
    parts: List[str] = [source]
    for key, value in signals.items():
        if value is None:
            continue
        parts.append(f"{key}: {value}")
    if raw_excerpt:
        parts.append(raw_excerpt[:800])
    return " ".join(parts)


def store_evidence_event(
    *,
    session_id: Optional[str],
    host: str,
    source: str,
    signals: Dict[str, Any],
    raw_excerpt: str,
) -> None:
    """Store a parsed evidence event."""
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        text = _build_evidence_text(source, signals, raw_excerpt)
        embedding = None
        vector_literal = None
        try:
            embedding = embed_text(cfg.ollama_base_url, cfg.embed_model, text[:2000], cfg.embed_timeout_sec)
            vector_literal = _vector_literal(embedding)
        except Exception:
            vector_literal = None
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO evidence_events
                    (session_id, host, source, signals, raw_excerpt, tsv, embedding)
                VALUES
                    (%s, %s, %s, %s, %s, to_tsvector('english', %s), %s::vector)
                """,
                (
                    session_id,
                    host or "",
                    source,
                    _jsonb(signals),
                    raw_excerpt,
                    text,
                    vector_literal,
                ),
            )
        conn.commit()
    except Exception:
        # Evidence storage failures should not break primary flows.
        if conn is not None:
            conn.rollback()
    finally:
        if conn is not None:
            conn.close()


def load_recent_evidence(session_id: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Return recent evidence events for a session."""
    if not session_id:
        return []
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT host, source, event_time, signals, raw_excerpt
                FROM evidence_events
                WHERE session_id = %s
                ORDER BY event_time DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
        results = []
        for host, source, event_time, signals, raw_excerpt in rows:
            results.append(
                {
                    "host": host,
                    "source": source,
                    "event_time": event_time,
                    "signals": signals or {},
                    "raw_excerpt": raw_excerpt or "",
                }
            )
        return results
    finally:
        if conn is not None:
            conn.close()


def search_evidence(
    query: str,
    limit: int = 5,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search evidence events via hybrid ranking."""
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        embedding = embed_text(cfg.ollama_base_url, cfg.embed_model, query, cfg.embed_timeout_sec)
        vector_literal = _vector_literal(embedding)
        params: List[Any] = [query, vector_literal]
        where_clause = ""
        if session_id:
            where_clause = "WHERE session_id = %s"
            params.insert(0, session_id)
        sql = f"""
            SELECT host, source, event_time, signals, raw_excerpt,
                   ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS bm25_score,
                   1 - (embedding <=> %s::vector) AS vector_score,
                   CASE
                       WHEN event_time IS NULL THEN 0
                       ELSE 1 / (1 + (EXTRACT(EPOCH FROM (now() - event_time)) / 86400))
                   END AS recency_score
            FROM evidence_events
            {where_clause}
            ORDER BY (
                0.6 * ts_rank_cd(tsv, plainto_tsquery('english', %s)) +
                0.3 * (1 - (embedding <=> %s::vector)) +
                0.1 * CASE
                    WHEN event_time IS NULL THEN 0
                    ELSE 1 / (1 + (EXTRACT(EPOCH FROM (now() - event_time)) / 86400))
                END
            ) DESC
            LIMIT %s
        """
        params.extend([query, vector_literal, limit])
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        results = []
        for host, source, event_time, signals, raw_excerpt, *_ in rows:
            results.append(
                {
                    "host": host,
                    "source": source,
                    "event_time": event_time,
                    "signals": signals or {},
                    "raw_excerpt": raw_excerpt or "",
                }
            )
        return results
    finally:
        if conn is not None:
            conn.close()
