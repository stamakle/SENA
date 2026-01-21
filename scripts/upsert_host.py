"""Upsert a single host record into system_logs.

This helper is useful when you want to add a new hostname/service tag with
an IP for SSH without re-running the full ingestion pipeline.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from src.config import load_config
from src.db.postgres import get_connection, _jsonb, _vector_literal
from src.llm.ollama_client import embed_text


# Step 11: Helper script to upsert a host record into system_logs.


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the host upsert helper."""

    parser = argparse.ArgumentParser(description="Upsert a host into system_logs.")
    parser.add_argument("--system-id", help="Service tag or system ID.")
    parser.add_argument("--service-tag", help="Alias for --system-id.")
    parser.add_argument("--hostname", default="", help="Hostname to store.")
    parser.add_argument("--host-ip", default="", help="Primary host IP.")
    parser.add_argument("--idrac-ip", default="", help="iDRAC/BMC IP.")
    parser.add_argument("--model", default="", help="System model.")
    parser.add_argument("--rack", default="", help="Rack identifier.")
    parser.add_argument(
        "--metadata-json",
        default="",
        help="Optional JSON string to merge into metadata.",
    )
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding generation (uses NULL embedding).",
    )
    return parser.parse_args()


def _merge_metadata(args: argparse.Namespace, system_id: str) -> Dict[str, Any]:
    """Build metadata from CLI arguments and optional JSON."""

    metadata: Dict[str, Any] = {}
    if args.metadata_json:
        try:
            extra = json.loads(args.metadata_json)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata-json must be valid JSON") from exc
        if not isinstance(extra, dict):
            raise ValueError("metadata-json must be a JSON object")
        metadata.update(extra)

    # Explicit fields always win.
    if system_id:
        metadata["service tag"] = system_id
    if args.hostname:
        metadata["hostname"] = args.hostname
    if args.host_ip:
        metadata["host ip"] = args.host_ip
    if args.idrac_ip:
        metadata["idrac ip"] = args.idrac_ip
    return metadata


def upsert_host() -> None:
    """Upsert a single host record into system_logs."""

    args = _parse_args()
    system_id = args.system_id or args.service_tag
    if not system_id:
        raise ValueError("Provide --system-id or --service-tag.")

    metadata = _merge_metadata(args, system_id)
    text_for_tsv = " ".join(
        value
        for value in [
            args.hostname,
            system_id,
            args.model,
            args.rack,
            args.host_ip,
            args.idrac_ip,
        ]
        if value
    )

    embedding_literal = None
    cfg = load_config()
    if not args.no_embed:
        embedding = embed_text(
            cfg.ollama_base_url,
            cfg.embed_model,
            text_for_tsv or system_id,
            cfg.request_timeout_sec,
        )
        embedding_literal = _vector_literal(embedding)

    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
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
                    system_id,
                    args.hostname,
                    args.model,
                    args.rack,
                    _jsonb(metadata),
                    text_for_tsv,
                    embedding_literal,
                ),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()

    print(f"Upserted host {system_id} (hostname={args.hostname or 'n/a'}).")


if __name__ == "__main__":
    upsert_host()
