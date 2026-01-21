"""Hybrid retrieval pipeline for Postgres.

This module performs hybrid retrieval (BM25 + vector similarity), merges
results, and prepares chunks for reranking and context building.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from src.db.postgres import _vector_literal


# Step 6: Create the retrieval function.

TABLE_FILTERS: Dict[str, List[str]] = {
    "test_cases": ["case_id", "name", "status", "type"],
    "system_logs": ["system_id", "hostname", "model", "rack"],
}

MAX_SUMMARY_STEPS = 3


def _build_filter_clause(filters: Dict[str, str], allowed: Iterable[str]) -> Tuple[str, List[Any]]:
    """Build a SQL WHERE clause and parameters from simple filters."""

    clauses = []
    params: List[Any] = []
    allowed_set = {field.lower() for field in allowed}
    for field, value in filters.items():
        if not value:
            continue
        if field.lower() not in allowed_set:
            continue
        clauses.append(f"{field} = %s")
        params.append(value)
    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def _search_table(
    conn,
    table: str,
    query: str,
    embedding: List[float],
    filters: Dict[str, str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Run a hybrid search against a single table."""

    allowed_filters = TABLE_FILTERS.get(table, [])
    vector_literal = _vector_literal(embedding)
    where_sql, params = _build_filter_clause(filters, allowed_filters)
    sql = f"""
        SELECT
            *,
            ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS bm25_score,
            1 - (embedding <=> %s::vector) AS vector_score
        FROM {table}
        {where_sql}
        ORDER BY (0.6 * ts_rank_cd(tsv, plainto_tsquery('english', %s)) + 0.4 * (1 - (embedding <=> %s::vector))) DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [query, vector_literal, *params, query, vector_literal, limit])
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]

    results = []
    for row in rows:
        payload = dict(zip(columns, row))
        payload["source_table"] = table
        results.append(payload)
    return results


def hybrid_search(
    conn,
    query: str,
    embedding: List[float],
    filters: Dict[str, str],
    limit: int,
    tables: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Search test cases and system logs and return merged results."""

    results: List[Dict[str, Any]] = []
    targets = list(tables) if tables else ["test_cases", "system_logs"]
    for table in targets:
        results.extend(_search_table(conn, table, query, embedding, filters, limit))
    return results


# Step 8: Build the answer context.


def extract_chunks(
    records: Iterable[Dict[str, Any]], step_mode: str = "summary"
) -> List[Dict[str, Any]]:
    """Convert raw DB rows into text chunks for reranking."""

    chunks: List[Dict[str, Any]] = []
    for record in records:
        if record.get("source_table") == "test_cases":
            steps_text: List[str] = []
            steps = record.get("steps") or []
            if isinstance(steps, list):
                if step_mode == "summary":
                    steps_iter = steps[:MAX_SUMMARY_STEPS]
                else:
                    steps_iter = steps
                for step in steps_iter:
                    if not isinstance(step, dict):
                        continue
                    label = step.get("step") or ""
                    desc = step.get("description") or ""
                    expected = step.get("expected") or ""
                    if step_mode == "detailed":
                        parts = [p for p in [label, desc, expected] if p]
                    else:
                        parts = [p for p in [label, desc] if p]
                    if parts:
                        steps_text.append(" ".join(parts))
            text = " ".join(
                part
                for part in [
                    record.get("name", ""),
                    record.get("description", ""),
                    record.get("precondition", ""),
                    " ".join(steps_text),
                ]
                if part
            )
            chunks.append(
                {
                    "id": record.get("case_id"),
                    "text": text,
                    "source": "test_cases",
                }
            )
        else:
            metadata = record.get("metadata") or {}
            meta_parts: List[str] = []
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    if value is None:
                        continue
                    key_lower = str(key).lower()
                    if "password" in key_lower or "passwd" in key_lower:
                        continue
                    if "secret" in key_lower or "token" in key_lower:
                        continue
                    text_value = str(value).strip()
                    if text_value:
                        meta_parts.append(f"{key}: {text_value}")
            text = " ".join(
                part
                for part in [
                    record.get("hostname", ""),
                    record.get("model", ""),
                    record.get("rack", ""),
                    " ".join(meta_parts),
                ]
                if part
            )
            chunks.append(
                {
                    "id": record.get("system_id"),
                    "text": text,
                    "source": "system_logs",
                }
            )
    return chunks
