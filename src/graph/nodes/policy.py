"""Policy node for displaying runtime guardrails."""

from __future__ import annotations

import json
from pathlib import Path

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict


def policy_node(state: GraphState | dict) -> dict:
    """Return current policy and guardrail settings."""

    current = coerce_state(state)
    cfg = load_config()
    ssh_path = Path(cfg.ssh_config_path)
    allowlist_count = 0
    if ssh_path.exists():
        try:
            data = json.loads(ssh_path.read_text(encoding="utf-8"))
            allowlist_count = len(data.get("allowlist", []) or [])
        except Exception:
            allowlist_count = 0
    live_commands_path = Path(__file__).resolve().parents[3] / "configs" / "live_commands.json"
    live_count = 0
    if live_commands_path.exists():
        try:
            payload = json.loads(live_commands_path.read_text(encoding="utf-8"))
            items = payload.get("commands", []) if isinstance(payload, dict) else payload
            live_count = len(items)
        except Exception:
            live_count = 0

    current.response = "\n".join(
        [
            "Policy summary:",
            f"- RAG mode: {cfg.rag_mode}",
            f"- RAG-only: {cfg.rag_only}",
            f"- Live strict mode: {cfg.live_strict_mode}",
            f"- Live auto-execute: {cfg.live_auto_execute}",
            f"- Allowlisted SSH commands: {allowlist_count}",
            f"- Registered /live commands: {live_count}",
        ]
    )
    return state_to_dict(current)
