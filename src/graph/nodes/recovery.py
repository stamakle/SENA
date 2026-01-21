"""Recovery node for suggesting safe fallbacks."""

from __future__ import annotations

import os
from pathlib import Path

from src.agent.live_memory import get_live_entry
from src.graph.state import GraphState, coerce_state, state_to_dict


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def _perform_oob_action(action: str, target: str) -> str:
    """Execute out-of-band actions like IPMI/BMC power control."""
    # In a real deployment, we would use 'ipmitool' or requests to BMC API.
    # checking for ipmitool availability
    # logger.info(f"OOB: {action} -> {target}")
    return f"[OOB-AUTOMATION] Executing '{action}' on target '{target}' via IPMI/Redfish... [SIMULATED OK]"


def recovery_node(state: GraphState | dict) -> dict:
    """Suggest recovery steps based on last output."""

    current = coerce_state(state)
    entry = get_live_entry(_live_path(), current.session_id) if current.session_id else None
    output = str(entry.get("output", "")).lower() if entry else ""

    steps = ["Recovery suggestions:"]
    if "timed out" in output:
        steps.extend(
            [
                "- Verify SSH reachability: /health <hostname>",
                "- Retry with shorter commands (e.g., /live uname <host>)",
                "- Increase LIVE_RACK_TIMEOUT_SEC for rack scans",
            ]
        )
    elif "unable to resolve" in output:
        steps.extend(
            [
                "- Verify system_logs has the host metadata",
                "- Use service tag instead of hostname",
                "- Run /inventory rack <RACK> to validate hosts",
            ]
        )
    elif "authentication failed" in output or "permission denied" in output:
        steps.extend(
            [
                "- Validate SSH credentials in configs/ssh.json",
                "- Run /live sudo-check <hostname> to confirm sudo access",
            ]
        )
    elif "no route to host" in output or "connection refused" in output:
        # Trigger OOB action
        action_log = _perform_oob_action("power cycle reference", current.hostname or "target-host")
        steps.extend(
            [
                "**Out-of-Band (OOB) Actions Triggered:**",
                "- SSH appears unreachable.",
                action_log,
                "- Please wait 180s for system boot and retry connection.",
            ]
        )

    current.response = "\n".join(steps)
    return state_to_dict(current)
