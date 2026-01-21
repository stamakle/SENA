"""Connectivity worker for quick host reachability checks."""

from __future__ import annotations

import socket
import time
from typing import Dict

from src.tools.ssh_client import load_ssh_config, _resolve_host_config


def check_connectivity(
    host: str,
    config_path: str,
    port: int = 22,
    timeout_sec: int = 2,
) -> Dict[str, object]:
    """Check TCP connectivity to the resolved host."""

    try:
        resolved = _resolve_host_config(load_ssh_config(config_path), host)
        address = resolved.get("address") or host
    except Exception as exc:
        return {
            "host": host,
            "address": "",
            "port": port,
            "port_open": False,
            "latency_ms": None,
            "error": str(exc),
        }

    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    try:
        sock.connect((address, port))
        latency = (time.time() - start) * 1000.0
        return {
            "host": host,
            "address": address,
            "port": port,
            "port_open": True,
            "latency_ms": round(latency, 2),
            "error": "",
        }
    except Exception as exc:
        return {
            "host": host,
            "address": address,
            "port": port,
            "port_open": False,
            "latency_ms": None,
            "error": str(exc),
        }
    finally:
        sock.close()
