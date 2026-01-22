"""Live-RAG node that executes allowlisted SSH commands."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Tuple

import json
import csv
import zipfile

from src.config import load_config
from src.graph.state import GraphState, ToolRequest, ToolResult, coerce_state, state_to_dict
from src.agent.live_extract import extract_error_lines, summarize_errors
from src.agent.live_cache import (
    get_cached_output,
    set_cached_output,
    get_cached_failure,
    set_cached_failure,
)
from src.db.postgres import get_connection
from src.agent.live_memory import (
    clear_live_entry,
    get_live_entry,
    get_live_proposed,
    clear_live_proposed,
    set_live_entry,
    set_live_status,
    set_live_strict_mode,
    set_live_auto_execute,
    set_live_pending,
    set_live_proposed,
)
from src.agent.summary_live import summarize_live_output
from src.ingest.prepare_data import _read_tabular, _normalize_row
from src.tools.ssh_client import load_ssh_config, run_ssh_command, _is_allowed
from src.domain.telemetry_parser import normalize_telemetry
from src.db.evidence_store import store_evidence_event

# P0 Recommendations Integration
from src.domain.circuit_breaker import get_circuit_breaker, CircuitState
from src.domain.parallel_ssh import ParallelSSHExecutor
from src.domain.dry_run import check_command_safety, format_confirmation_prompt
from src.domain.policy_engine import evaluate_command_policy


# Step 13: Live-RAG (SSH) node.


def _debug_enabled() -> bool:
    return os.getenv("RAG_DEBUG", "").lower() in {"1", "true", "yes"}


def _debug_log(message: str) -> None:
    if _debug_enabled():
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[LIVE_RAG DEBUG] {timestamp} {message}", flush=True)


def _live_commands_path() -> Path:
    """Return the custom live commands registry path."""

    return Path(
        os.getenv(
            "LIVE_COMMANDS_PATH",
            str(Path(__file__).resolve().parents[3] / "configs" / "live_commands.json"),
        )
    )


def _load_custom_commands() -> dict[str, dict]:
    """Load custom live command registry (name + aliases -> entry)."""

    path = _live_commands_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}

    items = []
    if isinstance(data, dict):
        items = data.get("commands", [])
    elif isinstance(data, list):
        items = data

    mapping: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        command = str(item.get("command", "")).strip()
        if not name or not command:
            continue
        entry = {
            "name": name,
            "command": command,
            "description": str(item.get("description", "")).strip(),
            "summary_default": bool(item.get("summary_default", False)),
            "aliases": [str(a).strip() for a in item.get("aliases", []) if str(a).strip()],
        }
        mapping[name] = entry
        for alias in entry["aliases"]:
            mapping[alias.lower()] = entry
    return mapping


def _custom_commands_help() -> str:
    """Return a help text block for custom commands."""

    mapping = _load_custom_commands()
    if not mapping:
        return ""
    seen = {}
    for entry in mapping.values():
        seen[entry["name"]] = entry
    lines = []
    for name, entry in sorted(seen.items()):
        desc = entry.get("description") or "custom command"
        lines.append(f"- /live {name} <hostname|service_tag>  ({desc})")
    return "\n".join(lines)


def _pending_commands_path() -> Path:
    """Return the pending commands registry path."""

    return Path(
        os.getenv(
            "LIVE_COMMANDS_PENDING_PATH",
            str(Path(__file__).resolve().parents[3] / "configs" / "live_commands_pending.json"),
        )
    )


def _load_registry_items() -> list[dict]:
    """Load custom command registry items for updates."""

    path = _live_commands_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if isinstance(data, dict):
        items = data.get("commands", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _save_registry_items(items: list[dict]) -> None:
    """Persist custom command registry items."""

    path = _live_commands_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"commands": items}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _load_pending_commands() -> list[dict]:
    """Load pending live command approvals."""

    path = _pending_commands_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if isinstance(data, dict):
        items = data.get("pending", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [item for item in items if isinstance(item, dict)]


def _save_pending_commands(items: list[dict]) -> None:
    """Persist pending live command approvals."""

    path = _pending_commands_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pending": items}
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _slugify_command(command: str) -> str:
    """Generate a safe command name slug from a command string."""

    lowered = re.sub(r"[^a-zA-Z0-9]+", "-", command.strip().lower())
    lowered = lowered.strip("-")
    return lowered[:40] or "custom-command"


def _queue_pending_command(command: str, source_query: str, summary_default: bool = False) -> str:
    """Queue a pending custom command and return its name."""

    pending = _load_pending_commands()
    existing_names = {str(item.get("name", "")).lower() for item in pending}
    base = _slugify_command(command)
    name = base
    counter = 1
    while name in existing_names:
        counter += 1
        name = f"{base}-{counter}"
    entry = {
        "name": name,
        "command": command,
        "aliases": [],
        "summary_default": summary_default,
        "description": "Pending approval",
        "source_query": source_query,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    pending.append(entry)
    _save_pending_commands(pending)
    return name


def _load_ssh_config_dict(cfg_path: str | Path) -> dict:
    """Load SSH config as a dict for mutation."""

    path = Path(cfg_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_ssh_config_dict(cfg_path: str | Path, data: dict) -> None:
    """Persist SSH config after mutation."""

    path = Path(cfg_path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _validate_custom_commands(
    mapping: dict[str, dict], allowlist: list[str]
) -> list[str]:
    """Validate registry entries and return warning strings."""

    warnings: list[str] = []
    if not mapping:
        return warnings
    allowset = set(cmd.strip() for cmd in allowlist or [])
    seen_names: set[str] = set()
    for key, entry in mapping.items():
        name = entry.get("name", "")
        command = entry.get("command", "")
        if name in seen_names:
            warnings.append(f"Duplicate command name: {name}")
        seen_names.add(name)
        if not command:
            warnings.append(f"Missing command for '{name}'")
            continue
        if command not in allowset:
            warnings.append(f"Not allowlisted: {command} (for /live {name})")
    return warnings


def _wants_raw_output(query: str) -> bool:
    """Return True when the user explicitly asks for raw/unfiltered output."""

    lowered = query.lower()
    if "raw" in lowered or "unfiltered" in lowered:
        return True
    if "full" in lowered and any(
        word in lowered
        for word in (
            "output",
            "log",
            "logs",
            "dmesg",
            "journal",
            "lscpu",
            "lspci",
            "lsblk",
            "nvme",
        )
    ):
        return True
    return False


def _wants_summary_output(query: str) -> bool:
    """Return True when the user explicitly asks for a summary output mode."""

    lowered = query.lower()
    return any(term in lowered for term in ("summary", "summarize", "issues", "key points"))


def _metadata_value(metadata: dict, keys: tuple[str, ...]) -> str:
    """Return the first matching metadata value for the given keys."""

    lowered = {str(k).lower(): v for k, v in metadata.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value:
            return str(value)
    return ""


def _extract_address_from_metadata(metadata: dict) -> str:
    """Extract a usable IP address from metadata."""

    return _metadata_value(
        metadata,
        (
            "host ip",
            "host  ip",
            "ip address",
            "management ip",
            "mgmt ip",
            "idrac ip",
            "bmc ip",
        ),
    ).strip()


def _extract_rack(query: str) -> str:
    """Extract rack identifier like B19 or rackD."""

    match = re.search(r"host[-_]?rack\s*([a-zA-Z]\d+|[a-zA-Z])", query, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper()
    match = re.search(r"rack\s*([a-zA-Z]\d+|[a-zA-Z])", query, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper()
    match = re.search(r"\brack([a-zA-Z]\d+|[a-zA-Z])\b", query, re.IGNORECASE)
    if match:
        return match.group(1).strip().upper()
    return ""


def _is_rack_nvme_query(query: str) -> bool:
    """Return True when the query asks for nvme list by rack."""

    lower = query.lower()
    if "rack" not in lower:
        return False
    if "nvme" in lower or "nvem" in lower or "ssd" in lower:
        return True
    if re.search(r"\bdrive(?:s)?\b", lower):
        return True
    if re.search(r"\bdisk(?:s)?\b", lower):
        return True
    return False


def _fetch_hosts_by_rack(rack: str, cfg) -> list[dict]:
    """Return list of host records for a rack."""

    rack_value = rack.strip().upper()
    if not rack_value:
        return []
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT system_id, hostname, metadata, rack
                FROM system_logs
                WHERE upper(rack) = %s
                   OR upper(metadata->>'rack') = %s
                """,
                (rack_value, rack_value),
            )
            rows = cur.fetchall()
        records = []
        for system_id, hostname, metadata, rack_col in rows:
            meta = metadata or {}
            address = _extract_address_from_metadata(meta)
            records.append(
                {
                    "system_id": str(system_id or ""),
                    "hostname": str(hostname or ""),
                    "address": address,
                    "rack": str(rack_col or meta.get("rack") or ""),
                }
            )
        if records:
            return records
    finally:
        if conn is not None:
            conn.close()
    if len(rack_value) == 1:
        records = _fetch_hosts_by_rack_prefix(rack_value, cfg)
        if records:
            return records
        return _fetch_hosts_by_rack_from_files(rack_value, allow_prefix=True)
    return _fetch_hosts_by_rack_from_files(rack_value, allow_prefix=False)


def _fetch_hosts_by_rack_prefix(rack_prefix: str, cfg) -> list[dict]:
    """Return host records for racks that start with the prefix."""

    prefix = rack_prefix.strip().upper()
    if not prefix:
        return []
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT system_id, hostname, metadata, rack
                FROM system_logs
                WHERE upper(rack) LIKE %s
                   OR upper(metadata->>'rack') LIKE %s
                """,
                (f"{prefix}%", f"{prefix}%"),
            )
            rows = cur.fetchall()
        records = []
        for system_id, hostname, metadata, rack_col in rows:
            meta = metadata or {}
            address = _extract_address_from_metadata(meta)
            records.append(
                {
                    "system_id": str(system_id or ""),
                    "hostname": str(hostname or ""),
                    "address": address,
                    "rack": str(rack_col or meta.get("rack") or ""),
                }
            )
        return records
    finally:
        if conn is not None:
            conn.close()


def _fetch_hosts_by_rack_from_files(rack_value: str, allow_prefix: bool) -> list[dict]:
    """Fallback: scan local system_logs files for rack metadata."""

    data_dir = Path(__file__).resolve().parents[3] / "data" / "system_logs"
    if not data_dir.exists():
        return []
    records = []
    seen = set()
    for path in data_dir.glob("*"):
        if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
            continue
        try:
            rows = _read_tabular(path)
        except Exception:
            continue
        for raw in rows:
            row = _normalize_row(raw)
            row_rack = row.get("rack", "").strip().upper()
            if allow_prefix:
                if not row_rack.startswith(rack_value):
                    continue
            elif row_rack != rack_value:
                continue
            system_id = row.get("service tag") or ""
            hostname = row.get("hostname") or ""
            address = _extract_address_from_metadata(row)
            key = (system_id, hostname, address)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "system_id": system_id,
                    "hostname": hostname,
                    "address": address,
                    "rack": row_rack,
                }
            )
    return records


def _suggest_racks(rack: str, cfg) -> list[str]:
    """Suggest nearby rack identifiers based on prefix matches."""

    rack_value = rack.strip().upper()
    if not rack_value:
        return []
    suggestions = set()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT rack, metadata->>'rack'
                FROM system_logs
                WHERE upper(rack) LIKE %s
                   OR upper(metadata->>'rack') LIKE %s
                """,
                (f"{rack_value}%", f"{rack_value}%"),
            )
            for rack_col, meta_rack in cur.fetchall():
                for value in (rack_col, meta_rack):
                    if value:
                        suggestions.add(str(value).strip().upper())
    finally:
        if conn is not None:
            conn.close()

    data_dir = Path(__file__).resolve().parents[3] / "data" / "system_logs"
    if data_dir.exists():
        for path in data_dir.glob("*"):
            if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
                continue
            try:
                rows = _read_tabular(path)
            except Exception:
                continue
            for raw in rows:
                row = _normalize_row(raw)
                value = row.get("rack", "").strip().upper()
                if value.startswith(rack_value):
                    suggestions.add(value)
    return sorted(suggestions)


def _parse_nvme_list_entries(output: str) -> list[dict]:
    """Extract NVMe details (drive, serial, model, firmware) from nvme list output."""

    lines = output.splitlines()
    header_idx = None
    header = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Node") and "SN" in stripped and "Model" in stripped:
            header_idx = idx
            header = line
            break

    def _fallback_entries() -> list[dict]:
        entries: list[dict] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("/dev/"):
                parts = stripped.split()
                entries.append(
                    {
                        "drive": parts[0],
                        "serial": "",
                        "model": "",
                        "firmware": "",
                    }
                )
        return entries

    if header_idx is None:
        return _fallback_entries()

    fw_label = "FW Rev" if "FW Rev" in header else ("FW" if "FW" in header else "")
    columns = {
        "drive": header.find("Node"),
        "serial": header.find("SN"),
        "model": header.find("Model"),
        "firmware": header.find(fw_label) if fw_label else -1,
    }
    if columns["drive"] < 0:
        return _fallback_entries()

    positions = sorted([(key, pos) for key, pos in columns.items() if pos >= 0], key=lambda x: x[1])

    def _slice(line: str, start: int, end: int | None) -> str:
        return line[start:end].strip() if end is not None else line[start:].strip()

    entries: list[dict] = []
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith("---"):
            continue
        if not stripped.startswith("/dev/"):
            continue
        values: dict[str, str] = {}
        for idx, (key, start) in enumerate(positions):
            end = positions[idx + 1][1] if idx + 1 < len(positions) else None
            values[key] = _slice(line, start, end)
        drive = values.get("drive", "")
        if not drive:
            continue
        entries.append(
            {
                "drive": drive,
                "serial": values.get("serial", ""),
                "model": values.get("model", ""),
                "firmware": values.get("firmware", ""),
            }
        )
    return entries


def _save_rack_nvme_csv(rack: str, rows: list[dict]) -> str:
    """Save rack NVMe list to CSV and return file path."""

    out_dir = Path(__file__).resolve().parents[3] / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"nvme_drives_rack_{rack}_{timestamp}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Rack",
                "service tag",
                "drive",
                "Serial Number (SN)",
                "Model",
                "Firmware",
                "status",
                "reason",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(path)


def _strip_sudo_prefix(command: str) -> str:
    """Return command without leading sudo prefix."""

    cleaned = command.strip()
    lowered = cleaned.lower()
    for prefix in ("sudo -n ", "sudo "):
        if lowered.startswith(prefix):
            return cleaned[len(prefix) :].strip()
    return cleaned


def _ensure_allowlist_entries(cfg_path: str | Path, commands: list[str]) -> None:
    """Ensure commands are present in the SSH allowlist."""

    if not commands:
        return
    ssh_cfg = _load_ssh_config_dict(cfg_path)
    allowlist = ssh_cfg.get("allowlist") or []
    updated = False
    for command in commands:
        cleaned = command.strip()
        if cleaned and cleaned not in allowlist:
            allowlist.append(cleaned)
            updated = True
    if updated:
        ssh_cfg["allowlist"] = allowlist
        _save_ssh_config_dict(cfg_path, ssh_cfg)


def _extract_nvme_devices(output: str) -> list[str]:
    """Extract /dev/nvmeXnY devices from nvme list or lsblk output."""

    if not output:
        return []
    matches = re.findall(r"/dev/nvme\d+n\d+|\bnvme\d+n\d+\b", output)
    devices = []
    for match in matches:
        if match.startswith("/dev/"):
            devices.append(match)
        else:
            devices.append(f"/dev/{match}")
    return sorted(set(devices))


def _nvme_controllers_from_devices(devices: list[str]) -> list[str]:
    """Return controller device names like nvme0 from nvme namespace devices."""

    controllers: set[str] = set()
    for device in devices:
        match = re.match(r"/dev/(nvme\d+)", device)
        if match:
            controllers.add(match.group(1))
    return sorted(controllers)


def _is_nvme_error_query(query: str) -> bool:
    """Return True when the query asks for NVMe errors or error logs."""

    lower = query.lower()
    if "nvme" not in lower:
        return False
    if "error" in lower or "errors" in lower:
        return True
    if "error-log" in lower or "error log" in lower or "error logs" in lower:
        return True
    if "smart-log" in lower or "smart log" in lower:
        return True
    return False


def _bundle_nvme_artifacts(artifact_dir: Path, bundle_name: str) -> Path:
    """Create a zip bundle from the NVMe artifact directory."""

    bundles_dir = artifact_dir.parent / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundles_dir / f"{bundle_name}.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for file_path in sorted(artifact_dir.rglob("*")):
            if file_path.is_file():
                arcname = f"{artifact_dir.name}/{file_path.relative_to(artifact_dir)}"
                bundle.write(file_path, arcname=arcname)
    return bundle_path


def _filter_nvme_lines(output: str) -> str:
    """Return only NVMe-related lines from a log output."""

    if not output:
        return ""
    hits = []
    for line in output.splitlines():
        lowered = line.lower()
        if "nvme" in lowered or "non-volatile" in lowered:
            hits.append(line)
    return "\n".join(hits).strip()


def _filter_lsblk_nvme(output: str) -> str:
    """Return lsblk lines for NVMe devices only."""

    if not output:
        return ""
    lines = output.splitlines()
    if not lines:
        return ""
    header = lines[0]
    hits = []
    if "name" in header.lower():
        hits.append(header)
    for line in lines[1:]:
        if re.search(r"\bnvme\d+n\d+\b", line):
            hits.append(line)
    return "\n".join(hits).strip()


def _filter_lspci_nvme_links(output: str) -> str:
    """Return NVMe PCI blocks with BDF + link info only."""

    if not output:
        return ""
    blocks = re.split(r"\n\s*\n", output.strip())
    filtered_blocks = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        lowered = block.lower()
        if "non-volatile memory controller" not in lowered and "nvme" not in lowered:
            continue
        header = lines[0].strip()
        link_lines = []
        for line in lines[1:]:
            l_lower = line.lower()
            if "lnkcap" in l_lower or "lnksta" in l_lower:
                link_lines.append(line.strip())
        filtered_blocks.append("\n".join([header] + link_lines))
    return "\n\n".join(filtered_blocks).strip()


def _filter_nvme_bundle_output(filename: str, output: str) -> str:
    """Filter bundle outputs to NVMe-specific lines where applicable."""

    if not output:
        return ""
    if filename == "lspci.log":
        return _filter_lspci_nvme_links(output)
    if filename == "lsblk.log":
        return _filter_lsblk_nvme(output)
    if filename in {"dmesg_err.log", "journal_err.log"}:
        return _filter_nvme_lines(output)
    return output.strip()


def _run_nvme_command(
    host: str,
    command: str,
    cfg,
) -> tuple[str, str]:
    """Run a single NVMe diagnostic command and return (output, error)."""

    base_command = _strip_sudo_prefix(command)
    _ensure_allowlist_entries(cfg.ssh_config_path, [base_command])
    command = _ensure_sudo(base_command)
    try:
        result = run_ssh_command(
            host,
            command,
            cfg.ssh_config_path,
            timeout_sec=cfg.request_timeout_sec,
        )
        if not result.success:
            return "", result.stderr or f"Command failed with exit {result.exit_code}"
        return result.stdout, ""
    except Exception as exc:
        return "", str(exc)


def _handle_nvme_error_bundle(current: GraphState, host: str, cfg, query: str) -> GraphState:
    """Collect NVMe diagnostics and bundle them for triage."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_host = re.sub(r"[^A-Za-z0-9_.-]+", "_", host.strip()) or "host"
    exports_dir = Path(__file__).resolve().parents[3] / "data" / "exports"
    artifact_dir = exports_dir / f"nvme_errors_{safe_host}_{timestamp}"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base_commands = [
        ("nvme_list.log", "nvme list"),
        ("lspci.log", "lspci -vv"),
        ("lsblk.log", "lsblk -o NAME,SIZE,MODEL,SERIAL"),
        ("dmesg_err.log", "dmesg -T --level=err,crit,alert,emerg | tail -n 200"),
        ("journal_err.log", "journalctl -k -p 3 -b --no-pager | tail -n 200"),
    ]

    raw_outputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    errors: list[str] = []
    command_map: dict[str, str] = {}

    for filename, command in base_commands:
        output, error = _run_nvme_command(host, command, cfg)
        command_map[filename] = command
        if error:
            raw_outputs[filename] = f"[ERROR] {error}"
            outputs[filename] = raw_outputs[filename]
            errors.append(f"{command}: {error}")
        else:
            raw_outputs[filename] = output
            filtered = _filter_nvme_bundle_output(filename, output)
            outputs[filename] = filtered or "No NVMe-related lines found."
        (artifact_dir / filename).write_text(outputs[filename], encoding="utf-8")
        if current.session_id and not error:
            signals = normalize_telemetry(filename, output)
            if signals:
                store_evidence_event(
                    session_id=current.session_id,
                    host=host,
                    source=filename,
                    signals=signals,
                    raw_excerpt=output[:4000],
                )

    nvme_entries = _parse_nvme_list_entries(raw_outputs.get("nvme_list.log", ""))
    devices = _extract_nvme_devices(raw_outputs.get("nvme_list.log", ""))
    if not devices:
        devices = _extract_nvme_devices(raw_outputs.get("lsblk.log", ""))
    controllers = _nvme_controllers_from_devices(devices)

    nvme_cmds = []
    for controller in controllers:
        device_path = f"/dev/{controller}"
        nvme_cmds.extend(
            [
                (f"nvme_smart_{controller}.log", f"nvme smart-log {device_path}"),
                (f"nvme_error_{controller}.log", f"nvme error-log {device_path}"),
                (f"nvme_fw_{controller}.log", f"nvme fw-log {device_path}"),
            ]
        )

    for filename, command in nvme_cmds:
        output, error = _run_nvme_command(host, command, cfg)
        command_map[filename] = command
        if error:
            outputs[filename] = f"[ERROR] {error}"
            errors.append(f"{command}: {error}")
        else:
            outputs[filename] = output.strip()
        (artifact_dir / filename).write_text(outputs[filename], encoding="utf-8")
        if current.session_id and not error:
            signals = normalize_telemetry(filename, output)
            if signals:
                store_evidence_event(
                    session_id=current.session_id,
                    host=host,
                    source=filename,
                    signals=signals,
                    raw_excerpt=output[:4000],
                )

    if nvme_entries:
        (artifact_dir / "nvme_devices.json").write_text(
            json.dumps(nvme_entries, indent=2),
            encoding="utf-8",
        )

    (artifact_dir / "commands.json").write_text(
        json.dumps(command_map, indent=2),
        encoding="utf-8",
    )

    error_sources = []
    for key, value in outputs.items():
        if "error" in key or "dmesg" in key or "journal" in key:
            error_sources.append(value)
    error_lines = extract_error_lines("\n".join(error_sources), max_lines=cfg.live_error_max_lines)

    bundle = _bundle_nvme_artifacts(artifact_dir, f"nvme_errors_{safe_host}_{timestamp}")

    summary_lines = [
        f"NVMe error bundle for {host}:",
        f"- Controllers: {', '.join(controllers) if controllers else 'none detected'}",
        f"- Commands run: {len(command_map)}",
        f"Bundle saved: {bundle}",
    ]
    summary_lines.append("Filtered to NVMe-only lines for lspci/lsblk/dmesg/journal.")
    lspci_filtered = outputs.get("lspci.log", "").strip()
    if lspci_filtered:
        summary_lines.append("NVMe PCIe link info:")
        summary_lines.append(lspci_filtered)
    if nvme_entries:
        summary_lines.append("Drives detected:")
        for entry in nvme_entries:
            summary_lines.append(
                f"- {entry.get('drive', '')} {entry.get('model', '')} {entry.get('serial', '')} {entry.get('firmware', '')}".strip()
            )
    if error_lines:
        summary_lines.append("Error-like lines:")
        summary_lines.append(error_lines)
    if errors:
        summary_lines.append("Command errors:")
        summary_lines.extend(f"- {item}" for item in errors[:10])

    summary_text = "\n".join(summary_lines)
    (artifact_dir / "summary.txt").write_text(summary_text, encoding="utf-8")
    current.response = summary_text

    if current.session_id:
        set_live_entry(
            _live_path(),
            current.session_id,
            summary_text,
            summary="",
            max_chars=cfg.live_output_max_chars,
            host=host,
            command="nvme-errors bundle",
            output_mode="summary",
        )
        current.last_live_output = summary_text
        current.last_live_summary = ""

    return current


def _extract_command(query: str) -> str:
    """Extract a command string from the query."""

    # Priority 1: Natural language pattern with pipe-aware matching
    # Match: Get/Run/Fetch <command possibly with pipes> from/on <host>
    # Note: We do this BEFORE quoted string extraction to handle commands that CONTAIN quotes (e.g. grep "foo")
    match = re.search(
        r"(?:run|execute|get|fetch|summarize)\s+(.+?)\s+(?:on|against|in|from)\s+[\w.-]+\s*$",
        query,
        re.IGNORECASE,
    )
    if match:
        cmd = match.group(1).strip()
        # If the WHOLE command is wrapped in quotes, strip them.
        # But be careful not to strip quotes that act as arguments (e.g. grep "foo") unless the whole thing is quoted.
        if (cmd.startswith("`") and cmd.endswith("`")) or \
           (cmd.startswith('"') and cmd.endswith('"')) or \
           (cmd.startswith("'") and cmd.endswith("'")):
            if len(cmd) > 2:
                cmd = cmd[1:-1].strip()
        
        _debug_log(f"command_extract matched NL pattern (with host): {cmd}")
        return cmd

    # Priority 2: Quoted commands (backticks, double quotes, single quotes)
    # Use this if no "Run ... on ..." structure is found
    match = re.search(r"`([^`]+)`", query)
    if match:
        _debug_log(f"command_extract matched backticks: {match.group(1).strip()}")
        return match.group(1).strip()
    match = re.search(r'"([^"]+)"', query)
    if match:
        _debug_log(f"command_extract matched double quotes: {match.group(1).strip()}")
        return match.group(1).strip()
    match = re.search(r"'([^']+)'", query)
    if match:
        _debug_log(f"command_extract matched single quotes: {match.group(1).strip()}")
        return match.group(1).strip()

    # Priority 3: Fallback - verb followed by rest of line
    match = re.search(r"(?:run|execute|get|fetch|summarize)\s+(.+)$", query, re.IGNORECASE)
    if match:
        cmd = match.group(1).strip()
        _debug_log(f"command_extract matched fallback: {cmd}")
        return cmd

    _debug_log("command_extract: no match found")
    return ""


def _extract_host(query: str) -> str:
    """Extract a hostname or service tag from the query."""

    host_blacklist = {
        "lscpu",
        "lspci",
        "lsblk",
        "dmesg",
        "journalctl",
        "nvme",
        "uname",
        "hostname",
        "ip",
        "cat",
        "that",
        "this",
        "last",
        "previous",
        "output",
        "log",
        "logs",
        "result",
        "the",
        "a",
        "an",
        "these",
        "those",
        "it",
        "its",
        "bundle",
        "errors",
    }

    match = re.search(r"^/ssh\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(
        r"(?:service\s*tag|service[-_]?tag|system\s*id|system_id)\s*[:#]?\s*([\w.-]+)",
        query,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(
        r"(?:hostname|host|server|system)\s*[:#]?\s*([\w.-]+)",
        query,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(
        r"(?:ssh\s+(?:to|into)\s+)(?:hostname|host|server|system)?\s*([\w.-]+)",
        query,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(r"on\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in host_blacklist:
            return candidate

    match = re.search(r"from\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in host_blacklist:
            return candidate

    match = re.search(r"\bin\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in host_blacklist and candidate.lower() not in {"rack", "racks"}:
            return candidate

    match = re.search(r"\bfor\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in host_blacklist and candidate.lower() not in {"rack", "racks"}:
            return candidate

    return ""


def _extract_host_hint(query: str) -> str:
    """Extract a host-like token when the query omits prepositions."""

    match = re.search(r"\b(?=[A-Za-z0-9_-]{6,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b", query)
    return match.group(0).strip() if match else ""


def _parse_live_request(query: str) -> Tuple[str, str]:
    """Return (host, command) parsed from the query."""

    host = _extract_host(query)
    command = _extract_command(query)
    return host, command


def _extract_quoted_command(query: str) -> str:
    """Extract a command only when it is quoted."""

    match = re.search(r"`([^`]+)`", query)
    if match:
        return match.group(1).strip()
    match = re.search(r'"([^"]+)"', query)
    if match:
        return match.group(1).strip()
    match = re.search(r"'([^']+)'", query)
    if match:
        return match.group(1).strip()
    return ""


def _parse_strict_ssh(query: str) -> Tuple[str, str]:
    """Parse /ssh HOST "command" or /ssh HOST `command`."""

    if not query.lower().startswith("/ssh"):
        return "", ""
    parts = query.split(maxsplit=2)
    if len(parts) < 3:
        return "", ""
    host = parts[1].strip()
    cmd = _extract_quoted_command(parts[2])
    if not cmd:
        return "", ""
    return host, cmd


def _parse_strict_freeform(query: str) -> Tuple[str, str]:
    """Parse strict freeform: Get/Fetch/Run `<cmd>` from <host>."""

    cmd = _extract_quoted_command(query)
    if not cmd:
        return "", ""
    host = _extract_host(query)
    if not host:
        return "", ""
    return host, cmd


def _strict_template_error() -> str:
    """Return strict mode guidance."""

    return (
        "Strict mode is enabled. Use one of these templates:\n"
        "- /live <shortcut> <hostname|service_tag>\n"
        "- /ssh <hostname|service_tag> \"command\"\n"
        "- Get `command` from <hostname|service_tag>\n"
        "Examples:\n"
        "- /live dmesg aseda-VMware-Vm1\n"
        "- /ssh aseda-VMware-Vm1 \"dmesg | tail -n 200\"\n"
        "- Get `journalctl -k -p 3 -b --no-pager | tail -n 200` from aseda-VMware-Vm1"
    )


def _live_path() -> Path:
    """Return the session live storage path."""

    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def _resolve_strict_mode(current: GraphState, cfg) -> bool:
    """Resolve strict mode using session preference or config default."""

    strict = cfg.live_strict_mode
    if current.session_id:
        entry = get_live_entry(_live_path(), current.session_id)
        if entry and entry.get("strict_mode") is not None:
            strict = bool(entry.get("strict_mode"))
    return strict


def _resolve_auto_execute(current: GraphState, cfg) -> bool:
    """Resolve auto-execute using session preference or config default."""

    auto_execute = cfg.live_auto_execute
    if current.session_id:
        entry = get_live_entry(_live_path(), current.session_id)
        if entry and entry.get("auto_execute") is not None:
            auto_execute = bool(entry.get("auto_execute"))
    return auto_execute


def _auto_filter_command(command: str, force_raw: bool = False) -> str:
    """Apply safe filters to reduce noisy outputs."""

    if force_raw:
        return command
    lowered = command.lower()
    if "dmesg" in lowered and "--level" not in lowered and "-l " not in lowered:
        if "|" in command or re.search(r"\b(tail|head|grep)\b", lowered):
            return command
        filtered = re.sub(
            r"(?i)\bdmesg\b",
            "dmesg -T --level=err,crit,alert,emerg",
            command,
            count=1,
        )
        return f"{filtered} | tail -n 200"
    if "dmesg" in lowered and "|" not in command and not re.search(r"\b(tail|head|grep)\b", lowered):
        return f"{command} | tail -n 200"
    if "lspci -vv" in lowered and "|" not in command:
        return f"{command} | head -n 200"
    return command


def _ensure_sudo(command: str) -> str:
    """Prefix sudo for live commands unless already present."""

    cleaned = command.strip()
    lowered = cleaned.lower()
    if lowered.startswith("sudo -n ") or lowered.startswith("sudo -s ") or lowered.startswith("sudo -s -p ") or lowered.startswith("sudo -p "):
        return cleaned
    if lowered.startswith("sudo "):
        remainder = cleaned[5:].strip()
        return f"sudo -n {remainder}"
    return f"sudo -n {cleaned}"


def _check_circuit_breaker(host: str) -> tuple[bool, str]:
    """Check if host circuit breaker allows execution.
    
    Returns:
        (can_execute, message) - True if allowed, False with reason if blocked
    """
    try:
        breaker = get_circuit_breaker(host)
        if not breaker.can_execute():
            status = breaker.get_status()
            time_until_retry = int(status.get("time_until_retry", 600))
            minutes = time_until_retry // 60
            return False, (
                f"🔴 **Circuit Open for `{host}`**\n\n"
                f"This host has failed {status['failure_count']} times recently and is temporarily blocked.\n"
                f"Retry in approximately {minutes} minutes, or use `/live circuit reset {host}` to force retry.\n\n"
                f"Last failure: {status.get('last_failure', 'unknown')}"
            )
        return True, ""
    except Exception as e:
        # If circuit breaker fails, allow execution
        _debug_log(f"Circuit breaker check failed: {e}")
        return True, ""


def _record_circuit_success(host: str) -> None:
    """Record successful SSH execution for circuit breaker."""
    try:
        breaker = get_circuit_breaker(host)
        breaker.record_success()
    except Exception as e:
        _debug_log(f"Circuit breaker success record failed: {e}")


def _record_circuit_failure(host: str, error: str) -> None:
    """Record failed SSH execution for circuit breaker."""
    try:
        breaker = get_circuit_breaker(host)
        breaker.record_failure(error)
    except Exception as e:
        _debug_log(f"Circuit breaker failure record failed: {e}")


def _check_destructive_command(command: str, session_id: str | None) -> tuple[bool, str]:
    """Check if command is destructive and needs confirmation.
    
    Returns:
        (needs_confirmation, preview_message)
    """
    try:
        result = check_command_safety(command)
        if result.requires_confirmation:
            preview = format_confirmation_prompt(result)
            return True, preview
        return False, ""
    except Exception as e:
        _debug_log(f"Dry-run check failed: {e}")
        return False, ""




def live_rag_node(state: GraphState | dict) -> dict:
    """Execute an allowlisted SSH command and store the output."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    _debug_log(f"live_rag_node start query={query!r}")

    cfg = load_config()
    strict_mode = _resolve_strict_mode(current, cfg)
    auto_execute = _resolve_auto_execute(current, cfg)
    custom_commands = _load_custom_commands()

    if query.lower().startswith("/live"):
        return state_to_dict(_handle_live_command(current, query, strict_mode))

    rack = _extract_rack(query)
    if rack and _is_rack_nvme_query(query):
        return state_to_dict(_handle_rack_nvme(current, rack, cfg, query))

    if _is_nvme_error_query(query):
        host = _extract_host(query) or _extract_host_hint(query)
        if not host and current.session_id:
            entry = get_live_entry(_live_path(), current.session_id)
            if entry and str(entry.get("command", "")).strip().lower() == "nvme-errors bundle":
                cached_output = str(entry.get("output", "")).strip()
                if cached_output:
                    current.response = cached_output
                    return state_to_dict(current)
        if not host:
            current.response = "Missing host. Example: find nvme errors in 98HLZ86"
            return state_to_dict(current)
        if not auto_execute and not query.lower().startswith("/live"):
            current.response = (
                "Auto-execute is OFF. Run `/live nvme-errors <hostname|service_tag>` "
                "or `/live auto on` to continue."
            )
            return state_to_dict(current)
        return state_to_dict(_handle_nvme_error_bundle(current, host, cfg, query))

    if strict_mode:
        if query.lower().startswith("/ssh"):
            host, command = _parse_strict_ssh(query)
        else:
            host, command = _parse_strict_freeform(query)
        if not host or not command:
            current.response = _strict_template_error()
            return state_to_dict(current)
    else:
        host, command = _parse_live_request(query)
    _debug_log(f"parsed host={host!r} command={command!r}")

    force_raw = _wants_raw_output(query)
    output_mode = "summary" if _wants_summary_output(query) and not force_raw else ""

    if command:
        custom_entry = custom_commands.get(command.strip().lower())
        if custom_entry:
            command = custom_entry.get("command", command)
            if custom_entry.get("summary_default") and not output_mode and not force_raw:
                output_mode = "summary"

    if not host or not command:
        _debug_log("missing host or command, returning help")
        current.response = (
            "To run a live SSH command, include a hostname/service tag and a command.\n"
            "Example:\n"
            "- /ssh SERVICE_TAG_ABC123 \"uname -a\"\n"
            "- SSH to hostname my-host and run `nvme list`"
        )
        return state_to_dict(current)

    original_command = command
    command = _ensure_sudo(_auto_filter_command(command, force_raw=force_raw))
    _debug_log(f"after ensure_sudo command={command!r}")

    if not auto_execute:
        if not current.session_id:
            current.response = (
                "Auto-execute is OFF but no session is available to store a pending command. "
                "Use LIVE_AUTO_EXECUTE=1 or provide a session."
            )
            return state_to_dict(current)
        set_live_pending(_live_path(), current.session_id, host, command)
        current.response = (
            f"Parsed live command (pending):\n- Host: {host}\n- Command: {command}\n\n"
            "Run `/live execute` to proceed or `/live auto on` to always auto-execute."
        )
        return state_to_dict(current)

    current.tool_requests.append(
        ToolRequest(name="ssh", args={"host": host, "command": command})
    )

    try:
        try:
            ssh_cfg = load_ssh_config(cfg.ssh_config_path)
            allowlist = ssh_cfg.get("allowlist") or []
        except Exception:
            allowlist = []
        if allowlist and not _is_allowed(command, allowlist):
            if command and custom_entry:
                current.response = (
                    f"Command '{custom_entry.get('name', command)}' is registered but not allowlisted. "
                    f"Run `/live approve {custom_entry.get('name', 'command')}` to allow it."
                )
                return state_to_dict(current)
            if current.session_id:
                proposed_name = _slugify_command(original_command)
                set_live_proposed(_live_path(), current.session_id, proposed_name, original_command, query)
                current.response = (
                    "I can add this command, but I need approval first.\n"
                    f"Proposed name: `{proposed_name}`\n"
                    f"Approve with `/live approve {proposed_name}` or reject with `/live reject {proposed_name}`."
                )
                return state_to_dict(current)
            current.response = (
                "Command is not allowlisted. Provide a session or approve via `/live approve <name>`."
            )
            return state_to_dict(current)
        
        # Policy check
        policy_decision = evaluate_command_policy(
            command,
            user_context=query,
        )
        if not policy_decision.allowed:
            if policy_decision.requires_approval and current.session_id:
                set_live_pending(_live_path(), current.session_id, host, command)
                current.response = (
                    f"Policy requires approval for this command.\n"
                    f"Reason: {policy_decision.reason}\n"
                    "Approve with `/live execute` or include 'force' in the request if authorized."
                )
                return state_to_dict(current)
            current.response = f"Command blocked by policy: {policy_decision.reason}"
            return state_to_dict(current)

        # P0 #13: Circuit Breaker Check
        can_execute, circuit_msg = _check_circuit_breaker(host)
        if not can_execute:
            current.response = circuit_msg
            return state_to_dict(current)
        
        # P0 #12: Dry-Run Check for Destructive Commands
        needs_confirm, preview = _check_destructive_command(command, current.session_id)
        if needs_confirm:
            # Store pending destructive command for confirmation
            if current.session_id:
                set_live_pending(_live_path(), current.session_id, host, command)
            current.response = preview
            return state_to_dict(current)
        
        _debug_log(f"calling _execute_live_command host={host} command={command}")
        _execute_live_command(current, host, command, cfg, output_mode=output_mode)
        _debug_log(f"live command executed, response length={len(current.response or '')}")
        
        # P0 #13: Record success for circuit breaker
        _record_circuit_success(host)
    except Exception as exc:
        _debug_log(f"live command failed: {exc}")
        
        # P0 #13: Record failure for circuit breaker
        _record_circuit_failure(host, str(exc))
        
        current.tool_results.append(ToolResult(name="ssh", error=str(exc), host=host, command=command))
        allowlist = []
        try:
            ssh_cfg = load_ssh_config(cfg.ssh_config_path)
            allowlist = ssh_cfg.get("allowlist") or []
        except Exception:
            allowlist = []
        allowed_text = "\n".join(f"- {cmd}" for cmd in allowlist) if allowlist else "- (none configured)"
        current.response = (
            f"SSH failed: {exc}\n\n"
            "Allowed commands:\n"
            f"{allowed_text}\n\n"
            "Format:\n"
            "- /ssh <service_tag|hostname> \"command\""
        )

    return state_to_dict(current)


def _handle_rack_nvme(current: GraphState, rack: str, cfg, query: str) -> GraphState:
    """Run nvme list across all hosts in a rack and save CSV."""

    hosts = _fetch_hosts_by_rack(rack, cfg)
    if not hosts:
        suggestions = _suggest_racks(rack, cfg)
        if suggestions:
            current.response = (
                f"No systems found for rack {rack}. Did you mean: {', '.join(suggestions[:5])}\n"
                "Ensure system_logs has rack metadata."
            )
        else:
            current.response = (
                f"No systems found for rack {rack}. Ensure system_logs has rack metadata."
            )
        return current

    rows = []
    errors = []
    command = "nvme list"
    if "sudo" in query.lower():
        command = "sudo nvme list"

    host_records = []
    skipped = []
    for record in hosts:
        system_id = record.get("system_id", "")
        hostname = record.get("hostname", "")
        address = record.get("address", "")
        host_id = address or system_id or hostname
        label = system_id or hostname or address
        if system_id and hostname and system_id != hostname:
            label = f"{system_id} ({hostname})"
        if not host_id:
            skipped.append(
                {
                    "label": label,
                    "system_id": system_id,
                    "hostname": hostname,
                    "host_id": "",
                    "error": "missing host id",
                    "status": "skip system",
                    "reason": "missing host id",
                }
            )
            continue
        cached_failure = get_cached_failure(host_id, command, cfg.live_rack_failure_ttl_sec)
        if cached_failure:
            skipped.append(
                {
                    "label": label,
                    "system_id": system_id,
                    "hostname": hostname,
                    "host_id": host_id,
                    "error": f"skipped (cached failure): {cached_failure}",
                    "status": "skip system",
                    "reason": f"cached failure: {cached_failure}",
                }
            )
            continue
        host_records.append(
            {
                "label": label,
                "system_id": system_id,
                "hostname": hostname,
                "host_id": host_id,
            }
        )

    executor = ParallelSSHExecutor(
        max_concurrent=max(1, cfg.live_rack_max_workers),
        command_timeout_sec=cfg.live_rack_timeout_sec,
        connection_timeout_sec=cfg.live_rack_timeout_sec,
    )
    host_ids = [r["host_id"] for r in host_records]

    def _circuit_check(host_id: str) -> bool:
        breaker = get_circuit_breaker(host_id)
        return breaker.can_execute()

    batch_result = executor.execute_on_hosts(
        hosts=host_ids,
        command=command,
        ssh_config_path=cfg.ssh_config_path,
        circuit_check=_circuit_check,
    )

    # Process skipped entries
    for skipped_item in skipped:
        label = skipped_item.get("label", "")
        system_id = skipped_item.get("system_id", "")
        hostname = skipped_item.get("hostname", "")
        error = skipped_item.get("error", "")
        status = skipped_item.get("status", "skip system")
        reason = skipped_item.get("reason", "")
        errors.append(f"{label}: {error}")
        rows.append(
            {
                "Rack": rack,
                "service tag": system_id or hostname,
                "drive": "",
                "Serial Number (SN)": "",
                "Model": "",
                "Firmware": "",
                "status": status,
                "reason": reason or error,
            }
        )

    # Map host_id to record metadata
    host_meta = {r["host_id"]: r for r in host_records}
    for result in batch_result.results:
        meta = host_meta.get(result.host, {})
        label = meta.get("label", result.host)
        system_id = meta.get("system_id", "")
        hostname = meta.get("hostname", "")
        if result.success:
            get_circuit_breaker(result.host).record_success()
            entries = _parse_nvme_list_entries(result.output)
            if not entries:
                rows.append(
                    {
                        "Rack": rack,
                        "service tag": system_id or hostname,
                        "drive": "",
                        "Serial Number (SN)": "",
                        "Model": "",
                        "Firmware": "",
                        "status": "no drives",
                        "reason": "",
                    }
                )
            else:
                for entry in entries:
                    rows.append(
                        {
                            "Rack": rack,
                            "service tag": system_id or hostname,
                            "drive": entry.get("drive", ""),
                            "Serial Number (SN)": entry.get("serial", ""),
                            "Model": entry.get("model", ""),
                            "Firmware": entry.get("firmware", ""),
                            "status": "ok",
                            "reason": "",
                        }
                    )
        else:
            get_circuit_breaker(result.host).record_failure(result.error or "unknown error")
            set_cached_failure(result.host, command, result.error or "unknown error")
            errors.append(f"{label}: {result.error}")
            rows.append(
                {
                    "Rack": rack,
                    "service tag": system_id or hostname,
                    "drive": "",
                    "Serial Number (SN)": "",
                    "Model": "",
                    "Firmware": "",
                    "status": "skip system",
                    "reason": result.error or "unknown error",
                }
            )

    if not rows:
        current.response = (
            f"No NVMe drives found for rack {rack}. "
            f"Errors: {', '.join(errors) if errors else 'none'}"
        )
        return current

    csv_path = _save_rack_nvme_csv(rack, rows)
    skipped_hosts = len([r for r in rows if r.get("status") == "skip system"])

    def _md_escape(value: str) -> str:
        return str(value).replace("|", "/").replace("\n", " ").strip()

    headers = [
        "Rack",
        "service tag",
        "drive",
        "Serial Number (SN)",
        "Model",
        "Firmware",
        "status",
        "reason",
    ]
    table_lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        table_lines.append(
            "| "
            + " | ".join(_md_escape(row.get(key, "")) for key in headers)
            + " |"
        )

    summary_lines = [
        f"Rack {rack} NVMe inventory:",
        f"- Hosts checked: {len(hosts)}",
        f"- Drives found: {len([r for r in rows if r.get('drive')])}",
        f"- Hosts skipped: {skipped_hosts}",
        "",
        "\n".join(table_lines),
        "",
        f"CSV saved: {csv_path}",
    ]
    if errors:
        summary_lines.append("Errors:")
        summary_lines.extend(f"- {e}" for e in errors[:10])
    current.response = "\n".join(summary_lines)
    return current


def _handle_live_command(current: GraphState, query: str, strict_mode: bool) -> GraphState:
    """Handle /live helper commands."""

    cfg = load_config()
    parts = query.strip().split()
    action = parts[1].lower() if len(parts) > 1 else ""
    args = parts[2:]
    mode = args[0].lower() if args else ""
    target = args[0] if args else ""
    custom_commands = _load_custom_commands()
    custom_entry = custom_commands.get(action)

    if action not in {
        "last",
        "clear",
        "errors",
        "sudo-check",
        "commands",
        "pending",
        "approve",
        "reject",
        "dmesg",
        "summarize",
        "journal",
        "lscpu",
        "lspci",
        "lsblk",
        "ip",
        "uname",
        "nvme",
        "nvme-errors",
        "nvme-error",
        "os",
        "strict",
        "auto",
        "execute",
        "sudo",
        "nvme-fwlog",
        "rack",
    } and not custom_entry:
        custom_help = _custom_commands_help()
        current.response = (
            "Live command usage:\n"
            "- /live last\n"
            "- /live errors\n"
            "- /live clear\n"
            "- /live sudo-check <hostname|service_tag>\n"
            "- /live commands\n"
            "- /live pending\n"
            "- /live approve <name>\n"
            "- /live reject <name>\n"
            "- /live dmesg <hostname|service_tag>\n"
            "- /live dmesg raw <hostname|service_tag>\n"
            "- /live dmesg full <hostname|service_tag>\n"
            "- /live journal <hostname|service_tag>\n"
            "- /live lscpu <hostname|service_tag>\n"
            "- /live lspci <hostname|service_tag>\n"
            "- /live lsblk <hostname|service_tag>\n"
            "- /live ip <hostname|service_tag>\n"
            "- /live uname <hostname|service_tag>\n"
            "- /live nvme <hostname|service_tag>\n"
            "- /live nvme-errors <hostname|service_tag>\n"
            "- /live os <hostname|service_tag>\n"
            "- /live summarize\n"
            "- /live strict on|off|status\n"
            "- /live auto on|off|status\n"
            "- /live execute\n"
            "- /live last summary\n"
            "- /live last full\n"
            "- /live rack nvme <RACK>"
        )
        if custom_help:
            current.response += f"\nCustom commands:\n{custom_help}"
        return current

    if action == "sudo-check":
        host = target.strip()
        if not host:
            current.response = "Usage: /live sudo-check <hostname|service_tag>"
            return current
        try:
            result = run_ssh_command(host, "sudo -n true", cfg.ssh_config_path)
            if not result.success:
                raise RuntimeError(result.stderr or "sudo check failed")
            current.response = f"Sudo check passed for {host}."
            if current.session_id:
                set_live_status(
                    _live_path(),
                    current.session_id,
                    True,
                    "",
                )
        except Exception as exc:
            current.response = f"Sudo check failed: {exc}"
            if current.session_id:
                set_live_status(
                    _live_path(),
                    current.session_id,
                    False,
                    str(exc),
                )
        return current

    if action == "rack":
        if not args:
            current.response = (
                "Usage:\n"
                "- /live rack nvme <RACK>\n"
                "- /live rack <RACK>\n"
                "Example: /live rack nvme D1"
            )
            return current
        rack_value = ""
        if len(args) >= 2 and args[0].lower() in {"nvme", "ssd"}:
            rack_value = args[1]
        else:
            rack_value = args[0]
        rack_value = rack_value.strip().upper()
        if not rack_value:
            current.response = "Missing rack identifier. Example: /live rack nvme D1"
            return current
        query = f"nvme list from rack{rack_value}"
        return _handle_rack_nvme(current, rack_value, cfg, query)

    if action == "commands":
        mapping = _load_custom_commands()
        if not mapping:
            current.response = "No custom live commands are registered."
            return current
        try:
            ssh_cfg = load_ssh_config(cfg.ssh_config_path)
            allowlist = ssh_cfg.get("allowlist") or []
        except Exception:
            allowlist = []
        warnings = _validate_custom_commands(mapping, allowlist)
        custom_help = _custom_commands_help()
        response = "Custom live commands:\n"
        response += custom_help or "- (none)"
        if warnings:
            response += "\n\nRegistry warnings:\n" + "\n".join(f"- {w}" for w in warnings)
        current.response = response
        return current

    if action == "pending":
        pending = _load_pending_commands()
        if not pending:
            pending_lines = []
        else:
            pending_lines = [
                f"- {entry.get('name', 'unnamed')}: {entry.get('command', '')}"
                for entry in pending
            ]
        proposed = None
        if current.session_id:
            proposed = get_live_proposed(_live_path(), current.session_id)
        response_lines = []
        if pending_lines:
            response_lines.append("Pending custom commands:")
            response_lines.extend(pending_lines)
        if proposed:
            response_lines.append("Proposed command for this session:")
            response_lines.append(f"- {proposed.get('name')}: {proposed.get('command')}")
        if not response_lines:
            current.response = "No pending or proposed custom commands."
        else:
            current.response = "\n".join(response_lines)
        return current

    if action in {"approve", "reject"}:
        name = target.strip().lower() if target else ""
        pending = _load_pending_commands()
        entry = next((item for item in pending if str(item.get("name", "")).lower() == name), None)
        proposed = None
        if current.session_id and not entry:
            proposed = get_live_proposed(_live_path(), current.session_id)
            if proposed:
                if not name:
                    name = str(proposed.get("name", "")).lower()
                if name and str(proposed.get("name", "")).lower() != name:
                    proposed = None
        if action == "reject":
            if not entry and not proposed:
                current.response = "No pending or proposed command to reject."
                return current
            pending = [item for item in pending if str(item.get("name", "")).lower() != name]
            _save_pending_commands(pending)
            if proposed and current.session_id:
                clear_live_proposed(_live_path(), current.session_id)
            current.response = f"Rejected pending command '{name}'."
            return current

        registry_items = _load_registry_items()
        registry_names = {str(item.get("name", "")).lower() for item in registry_items}
        if entry or proposed:
            src = entry or proposed
            if name not in registry_names:
                registry_items.append(
                    {
                        "name": src.get("name", name),
                        "command": src.get("command", ""),
                        "aliases": src.get("aliases", []),
                        "summary_default": src.get("summary_default", False),
                        "description": src.get("description", "Approved command"),
                    }
                )
                _save_registry_items(registry_items)
            pending = [item for item in pending if str(item.get("name", "")).lower() != name]
            _save_pending_commands(pending)
            if proposed and current.session_id:
                clear_live_proposed(_live_path(), current.session_id)
        elif name in registry_names:
            pass
        else:
            current.response = "No pending or proposed command to approve."
            return current

        ssh_cfg = _load_ssh_config_dict(cfg.ssh_config_path)
        allowlist = ssh_cfg.get("allowlist") or []
        command = ""
        if entry:
            command = str(entry.get("command", "")).strip()
        elif proposed:
            command = str(proposed.get("command", "")).strip()
        if not command:
            for item in registry_items:
                if str(item.get("name", "")).lower() == name:
                    command = str(item.get("command", "")).strip()
                    break
        if command and command not in allowlist:
            allowlist.append(command)
            ssh_cfg["allowlist"] = allowlist
            _save_ssh_config_dict(cfg.ssh_config_path, ssh_cfg)
        current.response = f"Approved '{name}'. Allowlist updated."
        return current

    if custom_entry:
        host = target.strip()
        if not host:
            current.response = f"Usage: /live {custom_entry.get('name', action)} <hostname|service_tag>"
            return current
        command = custom_entry.get("command", "").strip()
        if not command:
            current.response = "Custom command is missing the command string."
            return current
        output_mode = ""
        if _wants_summary_output(query) and not _wants_raw_output(query):
            output_mode = "summary"
        elif custom_entry.get("summary_default") and not _wants_raw_output(query):
            output_mode = "summary"
        try:
            command = _ensure_sudo(command)
            try:
                ssh_cfg = load_ssh_config(cfg.ssh_config_path)
                allowlist = ssh_cfg.get("allowlist") or []
            except Exception:
                allowlist = []
            if allowlist and not _is_allowed(command, allowlist):
                current.response = (
                    f"Command '{custom_entry.get('name', action)}' is registered but not allowlisted. "
                    f"Run `/live approve {custom_entry.get('name', action)}` to allow it."
                )
                return current
            _execute_live_command(current, host, command, cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "dmesg":
        host = ""
        raw_mode = False
        summary_mode = False
        if args:
            if args[0].lower() in {"raw", "full"}:
                raw_mode = True
                host = args[1].strip() if len(args) > 1 else ""
            elif args[0].lower() in {"summary", "summarize"}:
                summary_mode = True
                host = args[1].strip() if len(args) > 1 else ""
            else:
                host = args[0].strip()
        if not host:
            current.response = "Usage: /live dmesg [raw|full] <hostname|service_tag>"
            return current
        command = (
            "dmesg | tail -n 200"
            if raw_mode
            else "dmesg -T --level=err,crit,alert,emerg | tail -n 200"
        )
        try:
            output_mode = "summary" if summary_mode else ""
            _execute_live_command(current, host, command, cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "journal":
        host = target.strip()
        if not host:
            current.response = "Usage: /live journal <hostname|service_tag>"
            return current
        try:
            _execute_live_command(
                current,
                host,
                "journalctl -k -p 3 -b --no-pager | tail -n 200",
                cfg,
            )
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "lscpu":
        host = target.strip()
        if not host:
            current.response = "Usage: /live lscpu <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "lscpu", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "lspci":
        host = target.strip()
        if not host:
            current.response = "Usage: /live lspci <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "lspci -nn", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "lsblk":
        host = target.strip()
        if not host:
            current.response = "Usage: /live lsblk <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "lsblk -o NAME,SIZE,MODEL,SERIAL", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "ip":
        host = target.strip()
        if not host:
            current.response = "Usage: /live ip <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "ip -4 addr show", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "uname":
        host = target.strip()
        if not host:
            current.response = "Usage: /live uname <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "uname -a", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "sudo":
        host = target.strip()
        if not host:
            current.response = "Usage: /live sudo <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "sudo -n true", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "nvme-fwlog":
        host = target.strip()
        if not host:
            current.response = "Usage: /live nvme-fwlog <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "nvme fw-log /dev/nvme0", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current
    
    if action in {"nvme-errors", "nvme-error"}:
        host = target.strip()
        if not host:
            current.response = "Usage: /live nvme-errors <hostname|service_tag>"
            return current
        return _handle_nvme_error_bundle(current, host, cfg, query)

    if action == "nvme":
        host = target.strip()
        if not host:
            current.response = "Usage: /live nvme <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "nvme list", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "os":
        host = target.strip()
        if not host:
            current.response = "Usage: /live os <hostname|service_tag>"
            return current
        try:
            output_mode = "summary" if _wants_summary_output(query) else ""
            _execute_live_command(current, host, "cat /etc/os-release", cfg, output_mode=output_mode)
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current

    if action == "strict":
        if not current.session_id:
            current.response = "No session is active to store strict mode. Set LIVE_STRICT_MODE=1 instead."
            return current
        if mode in {"on", "true", "1"}:
            set_live_strict_mode(_live_path(), current.session_id, True)
            current.response = "Strict mode enabled for this session."
            return current
        if mode in {"off", "false", "0"}:
            set_live_strict_mode(_live_path(), current.session_id, False)
            current.response = "Strict mode disabled for this session."
            return current
        current.response = f"Strict mode is {'ON' if strict_mode else 'OFF'}."
        return current

    if action == "auto":
        if not current.session_id:
            current.response = "No session is active to store auto-execute. Set LIVE_AUTO_EXECUTE=1 instead."
            return current
        if mode in {"on", "true", "1"}:
            set_live_auto_execute(_live_path(), current.session_id, True)
            current.response = "Auto-execute enabled for this session."
            return current
        if mode in {"off", "false", "0"}:
            set_live_auto_execute(_live_path(), current.session_id, False)
            current.response = "Auto-execute disabled for this session."
            return current
        current.response = "Auto-execute is ON." if _resolve_auto_execute(current, cfg) else "Auto-execute is OFF."
        return current

    if not current.session_id:
        current.response = "No session is active for live output retrieval."
        return current

    live_path = _live_path()

    if action == "summarize":
        entry = get_live_entry(live_path, current.session_id)
        if not entry:
            current.response = "No live output stored for this session yet."
            return current
        summary = str(entry.get("summary", "")).strip()
        if summary:
            current.response = f"Summary of the last live output:\n{summary}"
        else:
            output = str(entry.get("output", "")).strip()
            heuristic = summarize_errors(output, max_lines=cfg.live_error_max_lines)
            if heuristic:
                current.response = f"Summary of the last live output:\n{heuristic}"
            else:
                current.response = "No summary is available yet. Run another live command first."
        return current

    if action == "execute":
        entry = get_live_entry(live_path, current.session_id)
        if not entry or not entry.get("pending"):
            current.response = "No pending live command. Submit a command or turn auto-execute on."
            return current
        host = str(entry.get("host", "")).strip()
        command = str(entry.get("command", "")).strip()
        if not host or not command:
            current.response = "Pending command is missing host or command."
            return current
        try:
            _execute_live_command(current, host, command, cfg)
            entry = get_live_entry(live_path, current.session_id)
            if entry:
                entry["pending"] = False
        except Exception as exc:
            current.response = f"SSH failed: {exc}"
        return current
    if action == "clear":
        clear_live_entry(live_path, current.session_id)
        current.last_live_output = ""
        current.last_live_summary = ""
        current.response = "Cleared the last live output for this session."
        return current

    entry = get_live_entry(live_path, current.session_id)
    if not entry:
        current.response = "No live output stored for this session yet."
        return current

    output = str(entry.get("output", "")).strip()
    summary = str(entry.get("summary", "")).strip()
    if action == "errors":
        extracted = extract_error_lines(output, max_lines=cfg.live_error_max_lines)
        if extracted:
            current.response = f"Extracted error lines:\n{extracted}"
        else:
            current.response = "No error-like lines were found in the last live output."
        return current

    entry_mode = str(entry.get("output_mode", "")).strip().lower()
    resolved_mode = mode or entry_mode or cfg.live_output_mode.lower()
    if resolved_mode == "summary" and summary:
        current.response = f"Last live output (summary):\n{summary}"
    elif resolved_mode == "summary" and not summary:
        current.response = "No summary available. Use `/live last full` to view raw output."
    else:
        current.response = f"Last live output:\n{output or '[empty]'}"
    return current


def _execute_live_command(
    current: GraphState,
    host: str,
    command: str,
    cfg,
    output_mode: str = "",
) -> None:
    """Run a live command, summarize output, and persist it."""

    cached = get_cached_output(host, command, cfg.live_cache_ttl_sec)
    result = None
    if cached is not None:
        output = cached
    else:
        retries = max(0, int(cfg.live_retry_count))
        last_exc = None
        for attempt in range(retries + 1):
            try:
                result = run_ssh_command(
                    host,
                    command,
                    cfg.ssh_config_path,
                    timeout_sec=cfg.request_timeout_sec,
                )
                if not result.success:
                    raise RuntimeError(result.stderr or f"Command failed with exit {result.exit_code}")
                output = result.stdout
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        set_cached_output(host, command, output)
    current.tool_results.append(
        ToolResult(
            name="ssh",
            stdout=(result.stdout if result else output) or "",
            stderr=(result.stderr if result else ""),
            exit_code=(result.exit_code if result else None),
            duration_sec=(result.duration_sec if result else None),
            host=host,
            command=command,
        )
    )
    cleaned_output = _sanitize_output(output)
    summary = ""
    if cfg.live_summary_enabled and _should_summarize_output(cleaned_output or output):
        summary_input = cleaned_output or output
        if len(summary_input) > 6000:
            summary_input = summary_input[:6000]
        try:
            candidate = summarize_live_output(
                summary_input,
                cfg.ollama_base_url,
                cfg.live_summary_model,
                cfg.request_timeout_sec,
                cfg.live_summary_max_tokens,
            )
            if _summary_is_acceptable(candidate, cleaned_output or output):
                summary = candidate
        except Exception as exc:
            _debug_log(f"live summary failed: {exc}")

    response_body = cleaned_output or output
    is_summary = False
    mode = (output_mode or cfg.live_output_mode).lower()
    if mode == "summary":
        if summary:
            is_summary = True
            response_body = response_body or ""
            if "\n" in response_body:
                response_body = f"```\n{response_body}\n```"
            response_body = f"{response_body}\n\nSummary:\n{summary}"
        else:
            extracted = extract_error_lines(cleaned_output or output, max_lines=cfg.live_error_max_lines)
            response_body = extracted or cleaned_output or output

    if not is_summary and "\n" in response_body:
        response_body = f"```\n{response_body}\n```"

    current.response = f"SSH result for {host}:\n{response_body}"
    if current.session_id:
        live_path = _live_path()
        set_live_entry(
            live_path,
            current.session_id,
            cleaned_output or output,
            summary,
            max_chars=cfg.live_output_max_chars,
            host=host,
            command=command,
            output_mode=mode,
        )
        current.last_live_output = cleaned_output or output
        current.last_live_summary = summary
        # Store evidence from structured telemetry
        source_hint = command
        signals = normalize_telemetry(source_hint, cleaned_output or output)
        if signals:
            store_evidence_event(
                session_id=current.session_id,
                host=host,
                source=source_hint,
                signals=signals,
                raw_excerpt=(cleaned_output or output)[:4000],
            )


def _summary_is_grounded(summary: str, output: str) -> bool:
    """Return True when summary overlaps with output tokens."""

    if not summary or not output:
        return False
    output_tokens = set(re.findall(r"[A-Za-z0-9_-]{4,}", output.lower()))
    summary_tokens = set(re.findall(r"[A-Za-z0-9_-]{4,}", summary.lower()))
    if not output_tokens or not summary_tokens:
        return False
    overlap = output_tokens.intersection(summary_tokens)
    return len(overlap) >= max(1, min(3, len(summary_tokens) // 10 or 1))


_PROMPT_PATTERNS = [
    re.compile(r"^\[[^\]]+@[^\]]+\s[^\]]+\][#$]\s*$"),
    re.compile(r"^[\w.-]+@[^\s]+[:~\w/\-\.]+[#$]\s*$"),
]


def _sanitize_output(output: str) -> str:
    """Remove common shell prompt lines from output."""

    if not output:
        return output
    lines = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.match(stripped) for pattern in _PROMPT_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _should_summarize_output(output: str) -> bool:
    """Return True when output is large enough to summarize."""

    if not output:
        return False
    lines = output.splitlines()
    return len(output) >= 120 and len(lines) >= 3


def _summary_is_chatty(summary: str) -> bool:
    """Return True when summary looks like conversational filler."""

    lower = summary.lower()
    phrases = (
        "i'm trying to",
        "i am trying to",
        "could you",
        "please",
        "help me",
        "i found",
        "in this context",
        "this could be",
        "let me",
        "you may",
    )
    return any(phrase in lower for phrase in phrases)


def _summary_is_acceptable(summary: str, output: str) -> bool:
    """Return True when summary is grounded and not chatty."""

    if not summary:
        return False
    if _summary_is_chatty(summary):
        return False
    if not _summary_has_bullets(summary):
        return False
    return _summary_is_grounded(summary, output)


def _summary_has_bullets(summary: str) -> bool:
    """Return True if summary has at least two bullet/numbered lines."""

    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if not lines:
        return False
    bullet_like = 0
    for line in lines:
        if re.match(r"^[-*•]\s+", line):
            bullet_like += 1
        elif re.match(r"^\d+\.\s+", line):
            bullet_like += 1
    return bullet_like >= 2
