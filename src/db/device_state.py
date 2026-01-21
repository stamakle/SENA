"""Device State Manager (Flight Recorder).

Tracks the lifecycle of devices (host/DUT) over time.
Schema:
- table: device_history
- columns: timestamp, hostname, state (Healthy, Degraded, Missing, Busy), metadata (JSONB)
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from src.db.postgres import get_connection, _jsonb, _require_psycopg

def ensure_device_history_table(conn) -> None:
    """Ensure the device_history table exists."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS device_history (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ NOT NULL,
                hostname TEXT NOT NULL,
                state TEXT NOT NULL,
                metadata JSONB
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_device_history_hostname ON device_history(hostname)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_device_history_ts ON device_history(timestamp)")
    conn.commit()

def record_device_state(
    dsn: str,
    hostname: str,
    state: str,
    metadata: Dict[str, Any] | None = None
) -> None:
    """Record a snapshot of the device state."""
    conn = None
    try:
        conn = get_connection(dsn)
        ensure_device_history_table(conn)
        ts = datetime.now(timezone.utc)
        meta = metadata or {}
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO device_history (timestamp, hostname, state, metadata)
                VALUES (%s, %s, %s, %s)
                """,
                (ts, hostname, state, _jsonb(meta))
            )
        conn.commit()
    finally:
        if conn:
            conn.close()

def get_device_history(dsn: str, hostname: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve history for a device."""
    conn = None
    try:
        conn = get_connection(dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, state, metadata
                FROM device_history
                WHERE hostname = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (hostname, limit)
            )
            rows = cur.fetchall()
            
        return [
            {
                "timestamp": row[0].isoformat() if row[0] else "",
                "state": row[1],
                "metadata": row[2]
            }
            for row in rows
        ]
    except Exception:
        return []
    finally:
        if conn:
            conn.close()
