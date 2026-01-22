"""Incident knowledge base storage helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.config import load_config
from src.db.postgres import get_connection, _jsonb, _vector_literal
from src.llm.ollama_client import embed_text


def upsert_incident(
    incident_id: str,
    title: str,
    description: str,
    resolution: str,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert or update an incident record."""
    if not incident_id:
        return
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        text = " ".join(part for part in [title, description, resolution, " ".join(tags or [])] if part)
        embedding = embed_text(cfg.ollama_base_url, cfg.embed_model, text, cfg.embed_timeout_sec)
        vector_literal = _vector_literal(embedding)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO incidents (incident_id, title, description, resolution, tags, metadata, tsv, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('english', %s), %s::vector)
                ON CONFLICT (incident_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    resolution = EXCLUDED.resolution,
                    tags = EXCLUDED.tags,
                    metadata = EXCLUDED.metadata,
                    tsv = EXCLUDED.tsv,
                    embedding = EXCLUDED.embedding
                """,
                (
                    incident_id,
                    title,
                    description,
                    resolution,
                    _jsonb(tags or []),
                    _jsonb(metadata or {}),
                    text,
                    vector_literal,
                ),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def search_incidents(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search incidents via hybrid ranking."""
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        embedding = embed_text(cfg.ollama_base_url, cfg.embed_model, query, cfg.embed_timeout_sec)
        vector_literal = _vector_literal(embedding)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT incident_id, title, description, resolution, tags, metadata,
                       ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS bm25_score,
                       1 - (embedding <=> %s::vector) AS vector_score,
                       CASE
                           WHEN created_at IS NULL THEN 0
                           ELSE 1 / (1 + (EXTRACT(EPOCH FROM (now() - created_at)) / 86400))
                       END AS recency_score
                FROM incidents
                ORDER BY (
                    0.6 * ts_rank_cd(tsv, plainto_tsquery('english', %s)) +
                    0.3 * (1 - (embedding <=> %s::vector)) +
                    0.1 * CASE
                        WHEN created_at IS NULL THEN 0
                        ELSE 1 / (1 + (EXTRACT(EPOCH FROM (now() - created_at)) / 86400))
                    END
                ) DESC
                LIMIT %s
                """,
                (query, vector_literal, query, vector_literal, limit),
            )
            rows = cur.fetchall()
        results = []
        for incident_id, title, description, resolution, tags, metadata, *_ in rows:
            results.append(
                {
                    "incident_id": incident_id,
                    "title": title,
                    "description": description,
                    "resolution": resolution,
                    "tags": tags or [],
                    "metadata": metadata or {},
                }
            )
        return results
    finally:
        if conn is not None:
            conn.close()
