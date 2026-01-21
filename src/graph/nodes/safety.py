"""Safety node for approvals and guardrails."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List

from src.agent.live_memory import get_live_proposed
from src.graph.state import GraphState, coerce_state, state_to_dict


def _pending_commands_path() -> Path:
    return Path(
        os.getenv(
            "LIVE_PENDING_PATH",
            str(Path(__file__).resolve().parents[3] / "configs" / "live_commands_pending.json"),
        )
    )


def _load_pending_commands() -> List[dict]:
    path = _pending_commands_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data.get("pending", []) if isinstance(data, dict) else []


def safety_node(state: GraphState | dict) -> dict:
    """Surface pending approvals for live commands."""

    current = coerce_state(state)
    pending = _load_pending_commands()
    proposed = get_live_proposed(
        Path(os.getenv("SENA_LIVE_PATH", str(Path(__file__).resolve().parents[3] / "session_live.json"))),
        current.session_id or "",
    ) if current.session_id else None

    lines = ["Safety approvals:"]
    if pending:
        lines.append("Pending commands:")
        lines.extend([f"- {item.get('name')}: {item.get('command')}" for item in pending])
    else:
        lines.append("Pending commands: none.")

    if proposed:
        lines.append("")
        lines.append("Proposed command:")
        lines.append(f"- {proposed.get('name')}: {proposed.get('command')}")
        lines.append("Approve with /live approve <name> or reject with /live reject <name>.")
    else:
        lines.append("")
        lines.append("Proposed command: none.")

    current.response = "\n".join(lines)
    return state_to_dict(current)
