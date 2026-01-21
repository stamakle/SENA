"""Health check node for SSH reachability and sudo status."""

from __future__ import annotations

import re

from src.config import load_config
from src.agent.connectivity_worker import check_connectivity
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.tools.ssh_client import run_ssh_command


def _extract_host(query: str) -> str:
    match = re.search(r"(?:host|hostname|server|system)\s*[:#]?\s*([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bon\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bfrom\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def health_check_node(state: GraphState | dict) -> dict:
    """Check SSH connectivity and sudo readiness."""

    current = coerce_state(state)
    cfg = load_config()
    query = current.augmented_query or current.query
    host = _extract_host(query)
    if not host:
        current.response = "Missing host. Example: /health aseda-VMware-Vm1"
        return state_to_dict(current)

    connectivity = check_connectivity(host, cfg.ssh_config_path)
    lines = [
        f"Health check for {host}:",
        f"- Port open: {connectivity.get('port_open')}",
        f"- Address: {connectivity.get('address', '')}",
    ]
    if connectivity.get("error"):
        lines.append(f"- Connectivity error: {connectivity.get('error')}")

    sudo_ok = None
    if connectivity.get("port_open"):
        try:
            run_ssh_command(host, "sudo -n true", cfg.ssh_config_path, timeout_sec=cfg.request_timeout_sec)
            sudo_ok = True
        except Exception as exc:
            sudo_ok = False
            lines.append(f"- Sudo check failed: {exc}")
    if sudo_ok is True:
        lines.append("- Sudo check: OK")
    elif sudo_ok is False:
        lines.append("- Sudo check: FAIL")

    current.response = "\n".join(lines)
    return state_to_dict(current)
