"""Inventory node for NVMe device listings."""

from __future__ import annotations

import re

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.tools.ssh_client import run_ssh_command
from src.graph.nodes.live_rag import _extract_rack, _handle_rack_nvme


def _extract_host(query: str) -> str:
    match = re.search(r"(?:host|hostname|server|system)\s*[:#]?\s*([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bon\s+([\w.-]+)", query, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def inventory_node(state: GraphState | dict) -> dict:
    """List NVMe inventory for a host or rack."""

    current = coerce_state(state)
    cfg = load_config()
    query = current.augmented_query or current.query
    rack = _extract_rack(query)
    if rack:
        return state_to_dict(_handle_rack_nvme(current, rack, cfg, query))

    host = _extract_host(query)
    if not host:
        current.response = "Missing host or rack. Example: /inventory rack D1 or /inventory host aseda-VMware-Vm1"
        return state_to_dict(current)
    try:
        output = run_ssh_command(host, "nvme list", cfg.ssh_config_path, timeout_sec=cfg.request_timeout_sec)
        current.response = f"NVMe inventory for {host}:\n{output}"
    except Exception as exc:
        current.response = f"Inventory failed for {host}: {exc}"
    return state_to_dict(current)
