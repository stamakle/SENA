"""Ingest a single system_logs CSV/TSV file and upsert into Postgres.

This is a fast path when you only want to add one new system log file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.db.postgres import get_connection, upsert_system_logs
from src.ingest.prepare_data import _build_system_logs, _read_tabular
from src.llm.ollama_client import embed_text


# Step 11: Single-file system_logs ingest helper.


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the single-file ingest helper."""

    parser = argparse.ArgumentParser(description="Ingest a single system_logs file.")
    parser.add_argument("--input-file", required=True, help="Path to the CSV/TSV file.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of records per upsert batch.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=200,
        help="Print a progress message every N records.",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embeddings (uses zero vectors).",
    )
    return parser.parse_args()


def _chunks(items: List[dict], size: int) -> Iterable[List[dict]]:
    """Yield list chunks of the given size."""

    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def ingest_system_logs() -> None:
    """Read one file and upsert only system_logs."""

    args = _parse_args()
    input_path = Path(args.input_file)
    if not input_path.exists():
        raise FileNotFoundError(f"Missing input file: {input_path}")

    rows = _read_tabular(input_path)
    records = _build_system_logs(rows)

    cfg = load_config()
    if args.no_embed:
        zero_vector = [0.0] * cfg.embed_dim

        def embed_fn(_text: str) -> List[float]:
            return zero_vector

    else:

        def embed_fn(text: str) -> List[float]:
            return embed_text(
                cfg.ollama_base_url,
                cfg.embed_model,
                text,
                cfg.embed_timeout_sec,
            )

    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        total = 0
        for batch in _chunks(records, max(1, args.batch_size)):
            upsert_system_logs(conn, batch, embed_fn)
            total += len(batch)
            if args.progress_every and total % args.progress_every < len(batch):
                print(f"Upserted {total} system log records...")
        print(f"Done. Upserted {total} system log records.")
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    ingest_system_logs()
