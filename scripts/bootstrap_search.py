"""Bootstrap the Postgres search index from local data files.

This script is safe to run multiple times. It only indexes when the
search tables are empty. It also tolerates missing services so the UI
can still start even if Postgres/Ollama are not ready.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.config import load_config
from src.db.postgres import create_tables, ensure_extensions, get_connection
from src.ingest.prepare_data import prepare_data

try:
    from index_data import index_data
except Exception:  # pragma: no cover - defensive import for script usage
    index_data = None  # type: ignore[assignment]


def _count_rows(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        row = cur.fetchone()
    return int(row[0] or 0)


def _ensure_processed(raw_dir: Path, processed_dir: Path) -> bool:
    test_path = processed_dir / "test_cases.jsonl"
    system_path = processed_dir / "system_logs.jsonl"
    if test_path.exists() and system_path.exists():
        return True
    test_src = raw_dir / "test_cases"
    system_src = raw_dir / "system_logs"
    if not test_src.exists() or not system_src.exists():
        print(f"[WARN] Missing raw data under {raw_dir}. Skipping bootstrap.", flush=True)
        return False
    print(f"[INFO] Preparing data from {raw_dir} -> {processed_dir}", flush=True)
    prepare_data(raw_dir, processed_dir)
    return test_path.exists() and system_path.exists()


def main() -> int:
    if os.getenv("SENA_BOOTSTRAP_SEARCH", "1").lower() not in {"1", "true", "yes"}:
        print("[INFO] Search bootstrap disabled via SENA_BOOTSTRAP_SEARCH.", flush=True)
        return 0

    cfg = load_config()
    raw_dir = Path(os.getenv("SENA_RAW_DATA_DIR", "data"))
    processed_dir = Path(os.getenv("SENA_PROCESSED_DIR", "data/processed"))

    try:
        conn = get_connection(cfg.pg_dsn)
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[WARN] Postgres unavailable; search bootstrap skipped: {exc}", flush=True)
        return 0

    try:
        ensure_extensions(conn)
        create_tables(conn, cfg.embed_dim)
        test_count = _count_rows(conn, "test_cases")
        system_count = _count_rows(conn, "system_logs")
    except Exception as exc:
        print(f"[WARN] Failed checking search tables: {exc}", flush=True)
        return 0
    finally:
        conn.close()

    if test_count > 0 or system_count > 0:
        print("[INFO] Search index already populated. Skipping bootstrap.", flush=True)
        return 0

    if not _ensure_processed(raw_dir, processed_dir):
        return 0

    if index_data is None:
        print("[WARN] index_data module unavailable; search bootstrap skipped.", flush=True)
        return 0

    print("[INFO] Indexing data for search...", flush=True)
    try:
        index_data(processed_dir, limit=None, progress_every=50, skip_failures=True)
    except Exception as exc:
        print(f"[WARN] Search indexing failed: {exc}", flush=True)
        return 0

    print("[INFO] Search bootstrap complete.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
