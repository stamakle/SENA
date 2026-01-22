"""Telemetry parsing and normalization for SSD validation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.domain.smart_trends import parse_nvme_smart_log
from src.agent.live_extract import extract_error_lines


def _safe_json(text: str) -> Dict[str, Any] | None:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def parse_nvme_smart(raw: str) -> Dict[str, Any]:
    data = parse_nvme_smart_log(raw)
    signals: Dict[str, Any] = {}
    if isinstance(data, dict):
        for key in (
            "critical_warning",
            "temperature",
            "available_spare",
            "available_spare_threshold",
            "percentage_used",
            "media_errors",
            "num_err_log_entries",
            "error_log_entries",
            "unsafe_shutdowns",
            "power_cycles",
        ):
            if key in data:
                signals[key] = data.get(key)
    return signals


def parse_nvme_error_log(raw: str) -> Dict[str, Any]:
    signals: Dict[str, Any] = {}
    parsed = _safe_json(raw)
    if parsed:
        entries = parsed.get("errors") or parsed.get("error_log") or []
        signals["error_entries"] = len(entries) if isinstance(entries, list) else 0
        if isinstance(entries, list):
            statuses = []
            for entry in entries:
                status = entry.get("status") or entry.get("status_field")
                if status:
                    statuses.append(status)
            if statuses:
                signals["status_codes"] = statuses[:5]
        return signals

    status_matches = re.findall(r"status:\s*(0x[0-9a-fA-F]+)", raw)
    if status_matches:
        signals["status_codes"] = list(dict.fromkeys(status_matches))[:5]
    signals["error_entries"] = raw.lower().count("error")
    return signals


def parse_nvme_telemetry(raw: str) -> Dict[str, Any]:
    parsed = _safe_json(raw)
    if parsed:
        return {"telemetry_fields": list(parsed.keys())[:10]}
    return {"telemetry_fields": []}


def parse_dmesg(raw: str) -> Dict[str, Any]:
    signals: Dict[str, Any] = {}
    errors = extract_error_lines(raw, max_lines=50)
    if errors:
        signals["error_lines"] = errors.splitlines()[:10]
    signals["timeout_count"] = len(re.findall(r"timeout", raw, re.IGNORECASE))
    signals["reset_count"] = len(re.findall(r"reset", raw, re.IGNORECASE))
    signals["pcie_error_count"] = len(re.findall(r"aer|pcie|pcie bus error", raw, re.IGNORECASE))
    return signals


def parse_lspci(raw: str) -> Dict[str, Any]:
    signals: Dict[str, Any] = {}
    cap_match = re.search(r"LnkCap:\s*.*Speed\s*([0-9\.GT/s]+).*Width x(\d+)", raw)
    sta_match = re.search(r"LnkSta:\s*.*Speed\s*([0-9\.GT/s]+).*Width x(\d+)", raw)
    if cap_match:
        signals["link_cap_speed"] = cap_match.group(1)
        signals["link_cap_width"] = cap_match.group(2)
    if sta_match:
        signals["link_sta_speed"] = sta_match.group(1)
        signals["link_sta_width"] = sta_match.group(2)
    if "aer" in raw.lower():
        signals["aer_present"] = True
    return signals


def parse_nvme_id_ctrl(raw: str) -> Dict[str, Any]:
    signals: Dict[str, Any] = {}
    mqes_match = re.search(r"mqes\s*[:=]\s*([0-9]+)", raw, re.IGNORECASE)
    if mqes_match:
        signals["mqes"] = int(mqes_match.group(1))
    maxq_match = re.search(r"Max(?:imum)? Queue Entries\s*[:=]\s*([0-9]+)", raw, re.IGNORECASE)
    if maxq_match:
        signals["max_queue_entries"] = int(maxq_match.group(1))
    return signals


def normalize_telemetry(source: str, raw: str) -> Dict[str, Any]:
    """Normalize raw telemetry output into structured signals."""
    source_lower = source.lower()
    if "smart" in source_lower:
        return parse_nvme_smart(raw)
    if "error-log" in source_lower or "error_log" in source_lower:
        return parse_nvme_error_log(raw)
    if "telemetry" in source_lower:
        return parse_nvme_telemetry(raw)
    if "dmesg" in source_lower or "journal" in source_lower:
        return parse_dmesg(raw)
    if "lspci" in source_lower or "pcie" in source_lower:
        return parse_lspci(raw)
    if "id-ctrl" in source_lower or "show-regs" in source_lower:
        return parse_nvme_id_ctrl(raw)
    return {}
