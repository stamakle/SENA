"""Index prepared JSONL data into Postgres with pgvector.

This script loads the processed JSONL outputs and writes them into Postgres,
including text search vectors and embedding vectors.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.config import load_config
from src.db.postgres import (
    create_tables,
    ensure_extensions,
    get_connection,
)
from src.llm.ollama_client import embed_text, ensure_model, resolve_model, validate_embedding_model


# Step 6: Load data + build embeddings and indexes.


def _load_jsonl(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dictionaries."""

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit is not None and idx > limit:
                break
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _log_progress(label: str, index: int, total: int, every: int, skipped: int = 0) -> None:
    """Print progress every N records to show long-running activity."""

    if every <= 0:
        return
    if index % every == 0 or index == total:
        skip_info = f" (skipped: {skipped})" if skipped > 0 else ""
        print(f"[index] {label}: {index}/{total}{skip_info}", flush=True)


def _batch(records: List[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    """Yield records in fixed-size batches."""

    if size <= 0:
        yield records
        return
    for start in range(0, len(records), size):
        yield records[start : start + size]


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


def upsert_test_cases_safe(
    conn,
    records: Iterable[Dict[str, Any]],
    embed_fn,
    skip_failures: bool = False,
    cooldown_sec: float = 0.0,
) -> Tuple[int, int]:
    """Insert or update test case records. Returns (success_count, skip_count)."""

    success = 0
    skipped = 0
    with conn.cursor() as cur:
        for record in records:
            case_id = record.get("case_id", "unknown")
            try:
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
                success += 1
                if cooldown_sec > 0:
                    time.sleep(cooldown_sec)
            except Exception as exc:
                if skip_failures:
                    print(f"[WARN] Skipping test_case {case_id}: {exc}", flush=True)
                    skipped += 1
                    # Give Ollama time to recover after a crash
                    time.sleep(2.0)
                    continue
                else:
                    raise
    conn.commit()
    return success, skipped


def upsert_system_logs_safe(
    conn,
    records: Iterable[Dict[str, Any]],
    embed_fn,
    skip_failures: bool = False,
    cooldown_sec: float = 0.0,
) -> Tuple[int, int]:
    """Insert or update system log records. Returns (success_count, skip_count)."""

    success = 0
    skipped = 0
    with conn.cursor() as cur:
        for record in records:
            system_id = record.get("system_id", "unknown")
            try:
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
                success += 1
                if cooldown_sec > 0:
                    time.sleep(cooldown_sec)
            except Exception as exc:
                if skip_failures:
                    print(f"[WARN] Skipping system_log {system_id}: {exc}", flush=True)
                    skipped += 1
                    time.sleep(2.0)
                    continue
                else:
                    raise
    conn.commit()
    return success, skipped


def index_data(
    processed_dir: Path,
    limit: Optional[int],
    progress_every: int,
    skip_failures: bool = False,
    cooldown_sec: float = 0.0,
    batch_cooldown_sec: float = 0.0,
) -> None:
    """Index prepared JSONL data into Postgres."""

    cfg = load_config()
    resolved_embed_model = resolve_model(
        cfg.ollama_base_url, cfg.embed_model, cfg.request_timeout_sec
    )
    ensure_model(cfg.ollama_base_url, resolved_embed_model, cfg.request_timeout_sec)

    print(f"Validating embedding model {resolved_embed_model}...", flush=True)
    if not validate_embedding_model(cfg.ollama_base_url, resolved_embed_model, cfg.embed_timeout_sec):
        raise RuntimeError(
            f"Embedding model '{resolved_embed_model}' failed validation. "
            "It might be crashing due to low memory or corruption. "
            "Check 'ollama serve' logs or try 'ollama rm <model> && ollama pull <model>'."
        )
    test_path = processed_dir / "test_cases.jsonl"
    system_path = processed_dir / "system_logs.jsonl"

    if not test_path.exists():
        raise FileNotFoundError(f"Missing file: {test_path}")
    if not system_path.exists():
        raise FileNotFoundError(f"Missing file: {system_path}")

    conn = get_connection(cfg.pg_dsn)
    try:
        ensure_extensions(conn)
        create_tables(conn, cfg.embed_dim)

        def embed_fn(text: str) -> List[float]:
            safe_text = text.strip() or "empty record"
            return embed_text(
                cfg.ollama_base_url,
                resolved_embed_model,
                safe_text,
                cfg.embed_timeout_sec,
            )

        test_cases = _load_jsonl(test_path, limit=limit)
        system_logs = _load_jsonl(system_path, limit=limit)

        processed = 0
        total_skipped = 0
        total = len(test_cases)
        for batch in _batch(test_cases, progress_every):
            success, skipped = upsert_test_cases_safe(
                conn, batch, embed_fn, skip_failures=skip_failures, cooldown_sec=cooldown_sec
            )
            processed += len(batch)
            total_skipped += skipped
            _log_progress("test_cases", processed, total, progress_every, total_skipped)
            if batch_cooldown_sec > 0:
                time.sleep(batch_cooldown_sec)

        if total_skipped > 0:
            print(f"[WARN] Total test_cases skipped: {total_skipped}/{total}", flush=True)

        processed = 0
        total_skipped = 0
        total = len(system_logs)
        for batch in _batch(system_logs, progress_every):
            success, skipped = upsert_system_logs_safe(
                conn, batch, embed_fn, skip_failures=skip_failures, cooldown_sec=cooldown_sec
            )
            processed += len(batch)
            total_skipped += skipped
            _log_progress("system_logs", processed, total, progress_every, total_skipped)
            if batch_cooldown_sec > 0:
                time.sleep(batch_cooldown_sec)

        if total_skipped > 0:
            print(f"[WARN] Total system_logs skipped: {total_skipped}/{total}", flush=True)
    finally:
        conn.close()


def main() -> None:
    """CLI entry point for indexing prepared data."""

    parser = argparse.ArgumentParser(description="Index prepared JSONL into Postgres.")
    parser.add_argument(
        "--processed-dir",
        default="data/processed",
        help="Directory containing test_cases.jsonl and system_logs.jsonl",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for number of records to index from each file",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print progress every N records (also serves as batch size)",
    )
    parser.add_argument(
        "--skip-failures",
        action="store_true",
        help="Continue indexing even if individual records fail embedding",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=0.0,
        help="Seconds to wait between each record (helps unstable Ollama)",
    )
    parser.add_argument(
        "--batch-cooldown",
        type=float,
        default=0.0,
        help="Seconds to wait between batches (helps Ollama recover)",
    )
    args = parser.parse_args()

    index_data(
        Path(args.processed_dir),
        args.limit,
        args.progress_every,
        skip_failures=args.skip_failures,
        cooldown_sec=args.cooldown,
        batch_cooldown_sec=args.batch_cooldown,
    )


if __name__ == "__main__":
    main()
