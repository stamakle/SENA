"""SSH execution helper with allowlist enforcement (Paramiko).

This module is used by the ExecutionAgent for live RAG lookups.
"""

from __future__ import annotations

import json
import os
import re
import socket
from pathlib import Path
from typing import Iterable, List, Dict, Any

from src.config import load_config
from src.db.postgres import get_connection


def _is_ip(identifier: str) -> bool:
    """Return True when the identifier looks like an IPv4 address."""

    return bool(re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", identifier.strip()))

import paramiko


# Step 10: Add SSH execution with allowlists.


def _is_allowed(command: str, allowlist: Iterable[str]) -> bool:
    """Return True if the command is explicitly allowed."""

    allowed = set(allowlist)
    normalized = command.strip()
    if normalized in allowed:
        return True

    lowered = normalized.lower()
    for prefix in ("sudo -n ", "sudo -s ", "sudo -s -p '' ", "sudo -s -p \"\" ", "sudo -s ", "sudo -p '' ", "sudo -p \"\" ", "sudo "):
        if lowered.startswith(prefix):
            stripped = normalized[len(prefix) :].strip()
            return stripped in allowed or f"sudo {stripped}" in allowed
    return False


def _requires_sudo_password(stdout_text: str, stderr_text: str) -> bool:
    """Return True when sudo indicates a password is required."""

    combined = "\n".join([stdout_text or "", stderr_text or ""]).lower()
    if not combined.strip():
        return False
    hints = (
        "a password is required",
        "authentication failed",
        "sorry, try again",
        "not permitted",
        "permission denied",
        "sudo: a terminal is required",
        "interactive authentication is required",
        "sudo-rs: a password is required",
        "sudo-rs: interactive authentication is required",
    )
    return any(hint in combined for hint in hints)

def _debug_enabled() -> bool:
    return os.getenv("RAG_DEBUG", "").lower() in {"1", "true", "yes"}


def _debug_log(message: str) -> None:
    if _debug_enabled():
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[SSH DEBUG] {timestamp} {message}", flush=True)


def _exec_command(client: paramiko.SSHClient, command: str, timeout_sec: int, password: str | None) -> tuple[str, str]:
    """Execute a command and return (stdout, stderr)."""

    _debug_log(f"exec_command: {command!r} timeout={timeout_sec}")
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_sec, get_pty=True)
    if password:
        try:
            _stdin.write(password + "\n")
            _stdin.flush()
        except Exception:
            pass
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error_text = stderr.read().decode("utf-8", errors="replace").strip()
    if password:
        output = _strip_password_echo(output, password)
    _debug_log(f"exec_command output_len={len(output)} error_len={len(error_text)}")
    if len(output) < 500:
        _debug_log(f"exec_command output={output!r}")
    else:
        _debug_log(f"exec_command output_preview={output[:200]!r}...")
    return output, error_text


def _exec_command_with_status(
    client: paramiko.SSHClient,
    command: str,
    timeout_sec: int,
    password: str | None,
) -> tuple[str, str, int]:
    """Execute a command and return (stdout, stderr, exit_code)."""

    _debug_log(f"exec_command: {command!r} timeout={timeout_sec}")
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout_sec, get_pty=True)
    if password:
        try:
            _stdin.write(password + "\n")
            _stdin.flush()
        except Exception:
            pass
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error_text = stderr.read().decode("utf-8", errors="replace").strip()
    if password:
        output = _strip_password_echo(output, password)
        error_text = _strip_password_echo(error_text, password)
    exit_code = stdout.channel.recv_exit_status()
    _debug_log(f"exec_command output_len={len(output)} error_len={len(error_text)} rc={exit_code}")
    if len(output) < 500:
        _debug_log(f"exec_command output={output!r}")
    else:
        _debug_log(f"exec_command output_preview={output[:200]!r}...")
    return output, error_text, exit_code


def _strip_password_echo(output: str, password: str) -> str:
    """Remove echoed sudo passwords from output."""

    if not output or not password:
        return output
    lines = output.splitlines()
    filtered = [line for line in lines if line.strip() != password]
    return "\n".join(filtered).strip()


def load_ssh_config(path: str | Path) -> Dict[str, Any]:
    """Load SSH configuration from a JSON file."""

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Missing SSH config: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_host_config(config: Dict[str, Any], identifier: str) -> Dict[str, Any]:
    """Resolve SSH settings using RAG for host addressing."""

    hosts = config.get("hosts") or {}
    aliases = config.get("aliases") or {}

    resolved_key = aliases.get(identifier)
    if resolved_key is None:
        for key, host_cfg in hosts.items():
            if host_cfg.get("hostname") == identifier:
                resolved_key = key
                break
            if host_cfg.get("service_tag") == identifier:
                resolved_key = key
                break

    host_cfg = hosts.get(resolved_key, {}) if resolved_key else {}

    target = _resolve_target_from_rag(identifier, host_cfg)
    if _is_ip(identifier):
        address = identifier
    else:
        address = host_cfg.get("address") or target["address"]

    if not address:
        raise ValueError(
            f"Unable to resolve address for '{identifier}'. Ensure system_logs contains host IP metadata."
        )
    return {
        "address": address,
        "user": host_cfg.get("user") or config.get("default_user"),
        "port": host_cfg.get("port") or config.get("default_port", 22),
        "password": host_cfg.get("password") or config.get("default_password", ""),
        "key_path": host_cfg.get("key_path") or config.get("default_key_path", ""),
        "allowlist": host_cfg.get("allowlist") or config.get("allowlist") or [],
        "timeout_sec": host_cfg.get("timeout_sec") or config.get("timeout_sec", 5),
        "system_id": target.get("system_id", ""),
        "resolved_hostname": target.get("hostname", ""),
    }


def _metadata_value(metadata: Dict[str, Any], keys: Iterable[str]) -> str:
    """Return the first matching metadata value for the given keys."""

    lowered = {str(k).lower(): v for k, v in metadata.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value:
            return str(value)
    return ""


def _resolve_target_from_rag(identifier: str, host_cfg: Dict[str, Any]) -> Dict[str, str]:
    """Resolve the SSH address and identifiers from RAG (system_logs metadata)."""

    candidates = {
        identifier,
        host_cfg.get("hostname") or "",
        host_cfg.get("service_tag") or "",
    }
    candidates = {c for c in candidates if c}
    if not candidates:
        return {"address": "", "system_id": "", "hostname": ""}

    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT system_id, hostname, metadata
                FROM system_logs
                WHERE system_id = ANY(%s)
                   OR hostname = ANY(%s)
                   OR metadata->>'service tag' = ANY(%s)
                   OR metadata->>'hostname' = ANY(%s)
                LIMIT 1
                """,
                (list(candidates), list(candidates), list(candidates), list(candidates)),
            )
            row = cur.fetchone()

        if not row:
            return {"address": "", "system_id": "", "hostname": ""}

        system_id, hostname, metadata = row
        metadata = metadata or {}
        address = _metadata_value(
            metadata,
            [
                "host ip",
                "host  ip",
                "ip address",
                "management ip",
                "mgmt ip",
                "idrac ip",
                "bmc ip",
            ],
        )
        return {
            "address": address,
            "system_id": system_id or "",
            "hostname": hostname or _metadata_value(metadata, ["hostname"]),
        }
    finally:
        if conn is not None:
            conn.close()


def _update_hostname_if_needed(resolved: Dict[str, Any], client: paramiko.SSHClient) -> None:
    """Update system_logs.hostname after connecting when missing."""

    system_id = resolved.get("system_id") or ""
    if not system_id:
        return

    allowlist = set(resolved.get("allowlist") or [])
    hostname_cmd = None
    if "hostname" in allowlist:
        hostname_cmd = "hostname"
    elif "uname -n" in allowlist:
        hostname_cmd = "uname -n"

    if not hostname_cmd:
        return

    _stdin, stdout, _stderr = client.exec_command(
        hostname_cmd, timeout=int(resolved.get("timeout_sec", 5))
    )
    new_hostname = stdout.read().decode("utf-8", errors="replace").strip()
    if not new_hostname:
        return

    current = (resolved.get("resolved_hostname") or "").strip()
    if current and current.lower() == new_hostname.lower():
        return

    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE system_logs SET hostname = %s WHERE system_id = %s",
                (new_hostname, system_id),
            )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def run_ssh_command(
    host: str,
    command: str,
    config_path: str | Path,
    timeout_sec: int | None = None,
) -> str:
    """Run an allowlisted SSH command and return stdout text."""

    config = load_ssh_config(config_path)
    resolved = _resolve_host_config(config, host)
    allowlist = resolved["allowlist"]
    if not _is_allowed(command, allowlist):
        raise ValueError("Command is not allowlisted")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        key_filename = None
        key_path = resolved.get("key_path") or ""
        if key_path:
            key_file = Path(key_path).expanduser()
            if key_file.exists():
                key_filename = str(key_file)
            elif not resolved.get("password"):
                raise FileNotFoundError(
                    f"SSH key not found at {key_file}. Update configs/ssh.json or clear key_path to use a password."
                )

        effective_timeout = int(timeout_sec or resolved["timeout_sec"])
        base_kwargs = dict(
            port=int(resolved["port"]),
            username=resolved["user"],
            timeout=effective_timeout,
            auth_timeout=effective_timeout,
            banner_timeout=effective_timeout,
            allow_agent=True,
            look_for_keys=True,
        )

        candidates = []
        if not _is_ip(host):
            candidates.append(host)
        resolved_hostname = (resolved.get("resolved_hostname") or "").strip()
        if resolved_hostname and resolved_hostname not in candidates:
            candidates.append(resolved_hostname)
        address = resolved["address"]
        if address not in candidates:
            candidates.append(address)

        last_exc = None
        for candidate in candidates:
            try:
                client.connect(
                    hostname=candidate,
                    **base_kwargs,
                    password=None,
                    key_filename=key_filename,
                )
                last_exc = None
                break
            except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
                if not resolved.get("password"):
                    last_exc = exc
                    continue
                try:
                    client.connect(
                        hostname=candidate,
                        **base_kwargs,
                        password=resolved["password"],
                        key_filename=None,
                    )
                    last_exc = None
                    break
                except Exception as inner_exc:  # noqa: BLE001 - fallback chain
                    last_exc = inner_exc
                    continue
            except (socket.gaierror, OSError, paramiko.ssh_exception.NoValidConnectionsError) as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc

        _update_hostname_if_needed(resolved, client)

        timeout = effective_timeout
        password = resolved.get("password") or None
        sudo_mode = command.strip().lower().startswith("sudo ")
        sudo_n_mode = command.strip().lower().startswith("sudo -n ")

        if sudo_n_mode:
            output, error_text = _exec_command(client, command, timeout, None)
            if _requires_sudo_password(output, error_text) and password:
                base = command.strip()[len("sudo -n ") :].strip()
                sudo_command = f"sudo -S -p '' {base}"
                output, error_text = _exec_command(client, sudo_command, timeout, password)
        elif sudo_mode and password:
            base = command.strip()[len("sudo ") :].strip()
            sudo_command = f"sudo -S -p '' {base}"
            output, error_text = _exec_command(client, sudo_command, timeout, password)
        else:
            output, error_text = _exec_command(client, command, timeout, None)

        if error_text:
            raise RuntimeError(error_text)
        return output
    finally:
        client.close()


def run_ssh_command_with_status(
    host: str,
    command: str,
    config_path: str | Path,
    timeout_sec: int | None = None,
) -> tuple[str, str, int]:
    """Run an allowlisted SSH command and return stdout, stderr, exit code."""

    config = load_ssh_config(config_path)
    resolved = _resolve_host_config(config, host)
    allowlist = resolved["allowlist"]
    if not _is_allowed(command, allowlist):
        raise ValueError("Command is not allowlisted")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        key_filename = None
        key_path = resolved.get("key_path") or ""
        if key_path:
            key_file = Path(key_path).expanduser()
            if key_file.exists():
                key_filename = str(key_file)
            elif not resolved.get("password"):
                raise FileNotFoundError(
                    f"SSH key not found at {key_file}. Update configs/ssh.json or clear key_path to use a password."
                )

        effective_timeout = int(timeout_sec or resolved["timeout_sec"])
        base_kwargs = dict(
            port=int(resolved["port"]),
            username=resolved["user"],
            timeout=effective_timeout,
            auth_timeout=effective_timeout,
            banner_timeout=effective_timeout,
            allow_agent=True,
            look_for_keys=True,
        )

        candidates = []
        if not _is_ip(host):
            candidates.append(host)
        resolved_hostname = (resolved.get("resolved_hostname") or "").strip()
        if resolved_hostname and resolved_hostname not in candidates:
            candidates.append(resolved_hostname)
        address = resolved["address"]
        if address not in candidates:
            candidates.append(address)

        last_exc = None
        for candidate in candidates:
            try:
                client.connect(
                    hostname=candidate,
                    **base_kwargs,
                    password=None,
                    key_filename=key_filename,
                )
                last_exc = None
                break
            except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
                if not resolved.get("password"):
                    last_exc = exc
                    continue
                try:
                    client.connect(
                        hostname=candidate,
                        **base_kwargs,
                        password=resolved["password"],
                        key_filename=None,
                    )
                    last_exc = None
                    break
                except Exception as inner_exc:  # noqa: BLE001
                    last_exc = inner_exc
                    continue
            except (socket.gaierror, OSError, paramiko.ssh_exception.NoValidConnectionsError) as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc

        _update_hostname_if_needed(resolved, client)

        timeout = effective_timeout
        password = resolved.get("password") or None
        sudo_mode = command.strip().lower().startswith("sudo ")
        sudo_n_mode = command.strip().lower().startswith("sudo -n ")

        if sudo_n_mode:
            output, error_text, rc = _exec_command_with_status(client, command, timeout, None)
            if _requires_sudo_password(output, error_text) and password:
                base = command.strip()[len("sudo -n ") :].strip()
                sudo_command = f"sudo -S -p '' {base}"
                output, error_text, rc = _exec_command_with_status(client, sudo_command, timeout, password)
        elif sudo_mode and password:
            base = command.strip()[len("sudo ") :].strip()
            sudo_command = f"sudo -S -p '' {base}"
            output, error_text, rc = _exec_command_with_status(client, sudo_command, timeout, password)
        else:
            output, error_text, rc = _exec_command_with_status(client, command, timeout, None)
        return output, error_text, rc
    finally:
        client.close()


def upload_file(
    host: str,
    local_path: str | Path,
    remote_path: str,
    config_path: str | Path,
    timeout_sec: int | None = None,
) -> None:
    """Upload a local file to the remote host via SFTP."""

    config = load_ssh_config(config_path)
    resolved = _resolve_host_config(config, host)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        key_filename = None
        key_path = resolved.get("key_path") or ""
        if key_path:
            key_file = Path(key_path).expanduser()
            if key_file.exists():
                key_filename = str(key_file)
            elif not resolved.get("password"):
                raise FileNotFoundError(
                    f"SSH key not found at {key_file}. Update configs/ssh.json or clear key_path to use a password."
                )

        effective_timeout = int(timeout_sec or resolved["timeout_sec"])
        base_kwargs = dict(
            port=int(resolved["port"]),
            username=resolved["user"],
            timeout=effective_timeout,
            auth_timeout=effective_timeout,
            banner_timeout=effective_timeout,
            allow_agent=True,
            look_for_keys=True,
        )

        candidates = []
        if not _is_ip(host):
            candidates.append(host)
        resolved_hostname = (resolved.get("resolved_hostname") or "").strip()
        if resolved_hostname and resolved_hostname not in candidates:
            candidates.append(resolved_hostname)
        address = resolved["address"]
        if address not in candidates:
            candidates.append(address)

        last_exc = None
        for candidate in candidates:
            try:
                client.connect(
                    hostname=candidate,
                    **base_kwargs,
                    password=None,
                    key_filename=key_filename,
                )
                last_exc = None
                break
            except (paramiko.AuthenticationException, paramiko.SSHException) as exc:
                if not resolved.get("password"):
                    last_exc = exc
                    continue
                try:
                    client.connect(
                        hostname=candidate,
                        **base_kwargs,
                        password=resolved["password"],
                        key_filename=None,
                    )
                    last_exc = None
                    break
                except Exception as inner_exc:  # noqa: BLE001
                    last_exc = inner_exc
                    continue
            except (socket.gaierror, OSError, paramiko.ssh_exception.NoValidConnectionsError) as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc

        sftp = client.open_sftp()
        remote_path = str(remote_path)
        remote_dir = os.path.dirname(remote_path)
        if remote_dir:
            parts = remote_dir.strip("/").split("/")
            current = ""
            for part in parts:
                current += f"/{part}"
                try:
                    sftp.stat(current)
                except IOError:
                    sftp.mkdir(current)
        local_path = Path(local_path)
        sftp.put(str(local_path), remote_path)
        try:
            mode = local_path.stat().st_mode & 0o777
            sftp.chmod(remote_path, mode)
        except Exception:
            pass
        sftp.close()
    finally:
        client.close()


def run_remote_python(
    host: str,
    script_content: str,
    config_path: str | Path,
    timeout_sec: int | None = None,
) -> str:
    """Run a Python script on the remote host."""
    import uuid
    
    # Create unique temp filenames
    run_id = uuid.uuid4().hex
    remote_tmp = f"/tmp/sena_script_{run_id}.py"
    local_tmp = Path(f"/tmp/sena_local_{run_id}.py")
    
    try:
        # Write content to local temp file
        local_tmp.write_text(script_content, encoding="utf-8")
        
        # Upload to remote
        upload_file(host, local_tmp, remote_tmp, config_path, timeout_sec)
        
        # Execute python3 on remote
        # We assume python3 is available.
        output = run_ssh_command(host, f"python3 {remote_tmp}", config_path, timeout_sec)
        
        # Cleanup remote file (best effort)
        try:
            run_ssh_command(host, f"rm {remote_tmp}", config_path, timeout_sec)
        except Exception:
            pass
            
        return output
    finally:
        # Cleanup local file
        if local_tmp.exists():
            local_tmp.unlink()


def run_nvme_json(
    host: str,
    subcommand: str,
    config_path: str | Path,
    timeout_sec: int | None = None,
) -> Dict[str, Any] | List[Any]:
    """Run an nvme command with -o json and parse output.
    
    Args:
        subcommand: The part after 'nvme', e.g. 'list' or 'smart-log /dev/nvme0'.
                    Do NOT include '-o json'.
    """
    # Ensure -o json is used. Check if user already added it to avoid dup.
    if "-o json" not in subcommand:
        cmd = f"sudo nvme {subcommand} -o json"
    else:
        cmd = f"sudo nvme {subcommand}"

    # We need to explicitly allow this command in the allowlist if it's not there.
    # But run_ssh_command checks allowlist.
    # The user must ensure "sudo nvme *" is allowed or specific commands.
    
    output = run_ssh_command(host, cmd, config_path, timeout_sec)
    
    # Attempt to find the start of JSON in case of noise (like sudo warnings)
    try:
        stripped = output.strip()
        if not stripped:
            return {}
            
        # Find first brace or bracket
        idx_brace = stripped.find('{')
        idx_bracket = stripped.find('[')
        
        start_idx = 0
        if idx_brace != -1 and idx_bracket != -1:
            start_idx = min(idx_brace, idx_bracket)
        elif idx_brace != -1:
            start_idx = idx_brace
        elif idx_bracket != -1:
            start_idx = idx_bracket
        else:
            # excessive fallback, maybe it is a simple number or string
            pass
            
        json_str = stripped[start_idx:]
        return json.loads(json_str)
    except json.JSONDecodeError as exc:
        return {
            "error": "Failed to parse NVMe JSON output",
            "raw_output": output,
            "details": str(exc)
        }

