"""Index prepared JSONL data into Postgres with pgvector.

This script loads the processed JSONL outputs and writes them into Postgres,
including text search vectors and embedding vectors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.config import load_config
from src.db.postgres import (
    create_tables,
    ensure_extensions,
    get_connection,
    upsert_system_logs,
    upsert_test_cases,
)
from src.llm.ollama_client import embed_text, ensure_model, resolve_model


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


def _log_progress(label: str, index: int, total: int, every: int) -> None:
    """Print progress every N records to show long-running activity."""

    if every <= 0:
        return
    if index % every == 0 or index == total:
        print(f"[index] {label}: {index}/{total}", flush=True)


def _batch(records: List[Dict[str, Any]], size: int) -> Iterator[List[Dict[str, Any]]]:
    """Yield records in fixed-size batches."""

    if size <= 0:
        yield records
        return
    for start in range(0, len(records), size):
        yield records[start : start + size]


def index_data(processed_dir: Path, limit: Optional[int], progress_every: int) -> None:
    """Index prepared JSONL data into Postgres."""

    cfg = load_config()
    resolved_embed_model = resolve_model(
        cfg.ollama_base_url, cfg.embed_model, cfg.request_timeout_sec
    )
    ensure_model(cfg.ollama_base_url, resolved_embed_model, cfg.request_timeout_sec)
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
                cfg.request_timeout_sec,
            )

        test_cases = _load_jsonl(test_path, limit=limit)
        system_logs = _load_jsonl(system_path, limit=limit)

        processed = 0
        total = len(test_cases)
        for batch in _batch(test_cases, progress_every):
            upsert_test_cases(conn, batch, embed_fn)
            processed += len(batch)
            _log_progress("test_cases", processed, total, progress_every)

        processed = 0
        total = len(system_logs)
        for batch in _batch(system_logs, progress_every):
            upsert_system_logs(conn, batch, embed_fn)
            processed += len(batch)
            _log_progress("system_logs", processed, total, progress_every)
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
        help="Print progress every N records",
    )
    args = parser.parse_args()

    index_data(Path(args.processed_dir), args.limit, args.progress_every)


if __name__ == "__main__":
    main()
