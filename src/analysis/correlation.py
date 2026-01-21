"""Correlation Analysis Module."""

from typing import List, Dict, Any
from src.db.postgres import get_connection

def find_fleet_correlations(dsn: str, error_signature: str, target_host: str) -> List[str]:
    """Find other hosts matching the error signature or metadata of the target."""
    # This is a simplified keyword-based correlation.
    # In a real system, we'd vector-search log embeddings.
    
    conn = None
    correlations = []
    try:
        conn = get_connection(dsn)
        with conn.cursor() as cur:
            # 1. Get metadata of target host
            cur.execute("SELECT metadata FROM system_logs WHERE hostname = %s", (target_host,))
            row = cur.fetchone()
            if not row:
                return ["Target host not found in DB."]
            
            target_meta = row[0] or {}
            fw_version = target_meta.get("firmware", "")
            model = target_meta.get("model", "")
            
            if not fw_version:
                return ["No firmware version metadata for target."]

            # 2. Find other hosts with same FW/Model that might have logs
            # We assume we might look up 'incidents' table if it existed, 
            # but here we just list peers for manual check.
            cur.execute(
                """
                SELECT hostname FROM system_logs 
                WHERE metadata->>'firmware' = %s 
                AND hostname != %s
                LIMIT 5
                """,
                (fw_version, target_host)
            )
            peers = [r[0] for r in cur.fetchall()]
            
            if peers:
                correlations.append(f"Peers with FW {fw_version}: {', '.join(peers)}")
            else:
                correlations.append(f"No peers found with FW {fw_version}")
                
    except Exception as e:
        correlations.append(f"DB Error: {e}")
    finally:
        if conn:
            conn.close()
            
    return correlations
