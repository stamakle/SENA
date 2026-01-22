
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.config import load_config
    from src.db.postgres import get_connection, create_tables
    
    cfg = load_config()
    conn = get_connection(cfg.pg_dsn)
    create_tables(conn, cfg.embed_dim)
    conn.close()
    print("Schema updated successfully.")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
