"""Policy node for displaying runtime guardrails."""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.domain.policy_engine import DEFAULT_POLICY


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

    policy_path = Path(os.getenv("SENA_POLICY_PATH", str(Path(__file__).resolve().parents[3] / "configs" / "policy.json")))
    if policy_path.exists():
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except Exception:
            policy = DEFAULT_POLICY
    else:
        policy = DEFAULT_POLICY
    approval_rules = len(policy.get("require_approval_patterns", []) or [])
    block_rules = len(policy.get("block_patterns", []) or [])

    current.response = "\n".join(
        [
            "Policy summary:",
            f"- RAG mode: {cfg.rag_mode}",
            f"- RAG-only: {cfg.rag_only}",
            f"- Live strict mode: {cfg.live_strict_mode}",
            f"- Live auto-execute: {cfg.live_auto_execute}",
            f"- Allowlisted SSH commands: {allowlist_count}",
            f"- Registered /live commands: {live_count}",
            f"- Policy file: {policy_path}",
            f"- Approval rules: {approval_rules}",
            f"- Block rules: {block_rules}",
        ]
    )
    return state_to_dict(current)
