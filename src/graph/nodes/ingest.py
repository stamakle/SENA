"""Data ingest node for importing new CSV/Excel files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.graph.state import GraphState, coerce_state, state_to_dict


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"


def _extract_path(query: str) -> str:
    for token in query.split():
        if "/" in token or token.endswith(".csv") or token.endswith(".xlsx"):
            return token.strip().strip("\"'.,;")
    return ""


def ingest_node(state: GraphState | dict) -> dict:
    """List or ingest data files for the RAG store."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    path_raw = _extract_path(query)
    run_now = any(term in query.lower() for term in ("run", "execute", "ingest now"))

    if not path_raw:
        candidates = sorted(DATA_DIR.rglob("*.csv")) + sorted(DATA_DIR.rglob("*.xlsx"))
        if not candidates:
            current.response = "No CSV/XLSX files found under data/."
            return state_to_dict(current)
        lines = ["Discovered data files:"]
        lines.extend([f"- {path}" for path in candidates[:20]])
        if len(candidates) > 20:
            lines.append(f"...and {len(candidates) - 20} more")
        lines.append("")
        lines.append("To ingest a file: /ingest <path> (add 'run' to execute)")
        current.response = "\n".join(lines)
        return state_to_dict(current)

    input_path = Path(path_raw).expanduser()
    if not input_path.is_absolute():
        input_path = (PROJECT_ROOT / input_path).resolve()
    if not input_path.exists():
        current.response = f"File not found: {input_path}"
        return state_to_dict(current)

    if not run_now:
        current.response = (
            f"Ready to ingest: {input_path}\n"
            "Run with: /ingest run <path>\n"
            "System logs ingestion uses scripts/ingest_system_logs.py for system_logs data."
        )
        return state_to_dict(current)

    python_exec = sys.executable or "python3"
    if "system_logs" in str(input_path):
        cmd = [
            python_exec,
            str(PROJECT_ROOT / "scripts" / "ingest_system_logs.py"),
            "--input-file",
            str(input_path),
        ]
    else:
        cmd = [
            python_exec,
            "-m",
            "src.ingest.prepare_data",
            "--input-dir",
            str(input_path.parent),
            "--output-dir",
            str(DATA_DIR / "processed"),
        ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        current.response = (
            f"Ingest command: {' '.join(cmd)}\n"
            f"Exit code: {proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
        )
    except Exception as exc:
        current.response = f"Ingest failed: {exc}"
    return state_to_dict(current)
