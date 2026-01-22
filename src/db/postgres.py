"""Postgres helpers for schema creation and data indexing.

This module creates tables, builds text and vector indexes, and stores
records for hybrid retrieval.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List


# Step 3: Store structured data in Postgres.
# Step 4: Build the text search indexes.
# Step 5: Build the vector index.


def _require_psycopg() -> Any:
    """Import psycopg lazily to avoid hard dependency during early setup."""

    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise RuntimeError("psycopg is required for Postgres access") from exc
    return psycopg


def _jsonb(value: Any) -> Any:
    """Wrap a Python object as JSONB for psycopg."""

    _require_psycopg()
    try:
        from psycopg.types.json import Jsonb  # type: ignore
    except Exception as exc:
        raise RuntimeError("psycopg Jsonb type is unavailable") from exc
    return Jsonb(value)


def _vector_literal(values: List[float]) -> str:
    """Build a pgvector literal string from a list of floats."""

    if not values:
        raise ValueError(
            "Embedding vector is empty. Ensure the Ollama embedding model is available."
        )
    return "[" + ",".join(str(v) for v in values) + "]"


def get_connection(dsn: str):
    """Return a psycopg connection using the provided DSN."""

    psycopg = _require_psycopg()
    return psycopg.connect(dsn)


def ensure_extensions(conn) -> None:
    """Ensure required Postgres extensions exist."""

    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()


def create_tables(conn, embed_dim: int) -> None:
    """Create tables and indexes needed for hybrid retrieval."""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS test_cases (
                case_id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT,
                type TEXT,
                description TEXT,
                precondition TEXT,
                steps JSONB,
                source TEXT,
                tsv TSVECTOR,
                embedding VECTOR({embed_dim})
            )
            """
        )
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS system_logs (
                system_id TEXT PRIMARY KEY,
                hostname TEXT,
                model TEXT,
                rack TEXT,
                metadata JSONB,
                tsv TSVECTOR,
                embedding VECTOR({embed_dim})
            )
            """
        )
        # Spec-RAG Table
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS specs (
                id SERIAL PRIMARY KEY,
                title TEXT,
                content TEXT,
                metadata JSONB,
                tsv TSVECTOR,
                embedding VECTOR({embed_dim})
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_test_cases_tsv ON test_cases USING GIN(tsv)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_system_logs_tsv ON system_logs USING GIN(tsv)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_specs_tsv ON specs USING GIN(tsv)")
    conn.commit()


def _build_text_for_tsv(record: Dict[str, Any]) -> str:
    """Build a plain text string used for keyword search."""

    parts = [
        record.get("name", ""),
        record.get("description", ""),
        record.get("precondition", ""),
    ]
    steps = record.get("steps") or []
    for step in steps:
        parts.append(step.get("description", ""))
        parts.append(step.get("expected", ""))
    return " ".join(p for p in parts if p)


def _safe_metadata_values(metadata: Dict[str, Any]) -> List[str]:
    """Return safe metadata values for indexing (exclude secrets)."""

    values: List[str] = []
    for key, value in metadata.items():
        if value is None:
            continue
        key_lower = str(key).lower()
        if "password" in key_lower or "passwd" in key_lower:
            continue
        if "secret" in key_lower or "token" in key_lower:
            continue
        text = str(value).strip()
        if text:
            values.append(text)
    return values


def _build_system_tsv(record: Dict[str, Any]) -> str:
    """Build a keyword search string for system log records."""

    base_parts = [
        record.get("hostname", ""),
        record.get("model", ""),
        record.get("rack", ""),
    ]
    metadata = record.get("metadata") or {}
    safe_values = _safe_metadata_values(metadata)
    return " ".join(p for p in [*base_parts, *safe_values] if p)


def upsert_test_cases(
    conn,
    records: Iterable[Dict[str, Any]],
    embed_fn: Callable[[str], List[float]],
) -> None:
    """Insert or update test case records and their embeddings."""

    with conn.cursor() as cur:
        for record in records:
            text_for_tsv = _build_text_for_tsv(record)
            embedding = embed_fn(text_for_tsv)
            vector_literal = _vector_literal(embedding)
            cur.execute(
                """
                INSERT INTO test_cases
                    (case_id, name, status, type, description, precondition, steps, source, tsv, embedding)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, to_tsvector('english', %s), %s::vector)
                ON CONFLICT (case_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    type = EXCLUDED.type,
                    description = EXCLUDED.description,
                    precondition = EXCLUDED.precondition,
                    steps = EXCLUDED.steps,
                    source = EXCLUDED.source,
                    tsv = EXCLUDED.tsv,
                    embedding = EXCLUDED.embedding
                """,
                (
                    record.get("case_id"),
                    record.get("name"),
                    record.get("status"),
                    record.get("type"),
                    record.get("description"),
                    record.get("precondition"),
                    _jsonb(record.get("steps") or []),
                    record.get("source"),
                    text_for_tsv,
                    vector_literal,
                ),
            )
    conn.commit()


def upsert_system_logs(
    conn,
    records: Iterable[Dict[str, Any]],
    embed_fn: Callable[[str], List[float]],
) -> None:
    """Insert or update system log records and their embeddings."""

    with conn.cursor() as cur:
        for record in records:
            text_for_tsv = _build_system_tsv(record)
            embedding = embed_fn(text_for_tsv)
            vector_literal = _vector_literal(embedding)
            cur.execute(
                """
                INSERT INTO system_logs
                    (system_id, hostname, model, rack, metadata, tsv, embedding)
                VALUES
                    (%s, %s, %s, %s, %s, to_tsvector('english', %s), %s::vector)
                ON CONFLICT (system_id) DO UPDATE SET
                    hostname = EXCLUDED.hostname,
                    model = EXCLUDED.model,
                    rack = EXCLUDED.rack,
                    metadata = EXCLUDED.metadata,
                    tsv = EXCLUDED.tsv,
                    embedding = EXCLUDED.embedding
                """,
                (
                    record.get("system_id"),
                    record.get("hostname"),
                    record.get("model"),
                    record.get("rack"),
                    _jsonb(record.get("metadata") or {}),
                    text_for_tsv,
                    vector_literal,
                ),
            )
    conn.commit()
