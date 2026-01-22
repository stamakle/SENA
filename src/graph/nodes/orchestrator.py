"""Multi-step tool orchestration for testcases and firmware updates."""

from __future__ import annotations

import json
import re
import tarfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
import sys

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.agent.debug_agent import analyze_logs
from src.agent.connectivity_worker import check_connectivity
from src.agent.log_parser import parse_logs
from src.agent.citation_worker import build_citations
from src.agent.testcase_registry import resolve_testcase_script, list_testcase_ids
from src.agent.audit_pipeline import run_audit_pipeline
from src.agent.testcase_status import append_run, update_run, latest_run, format_status
from src.agent.testcase_auditor import load_testcase, audit_testcase, format_audit_markdown
from src.domain.telemetry_parser import normalize_telemetry
from src.db.evidence_store import store_evidence_event
from src.domain.webhook_reporter import get_reporter
from src.domain.traceability import get_requirement_for_test, enrich_test_result_with_trace
from src.tools.ssh_client import (
    run_ssh_command,
    run_ssh_command_with_status,
    upload_file,
    load_ssh_config,
    _resolve_host_config,
)
from src.graph.nodes.live_rag import _extract_rack, _fetch_hosts_by_rack


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CUSTOM_TOOLS_DIR = PROJECT_ROOT / "data" / "custom_tools"
TESTCASE_DIR = CUSTOM_TOOLS_DIR / "testcase_scripts"
FIRMWARE_DIR = CUSTOM_TOOLS_DIR / "firmware_updater"
EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
BUNDLES_DIR = EXPORTS_DIR / "bundles"
STATUS_PATH = EXPORTS_DIR / "testcase_runs.json"


def _ensure_allowlist(command: str, config_path: str) -> None:
    """Append command to SSH allowlist if missing."""

    cfg = load_ssh_config(config_path)
    allowlist = cfg.get("allowlist") or []
    if command in allowlist:
        return
    allowlist.append(command)
    cfg["allowlist"] = allowlist
    with Path(config_path).open("w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2)


def _extract_case_id(query: str) -> str:
    match = re.search(r"\b(?:TC|DSSTC)-\d+\b", query, re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _extract_host(query: str) -> str:
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
    match = re.search(r"\bon\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\bfrom\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _extract_device(query: str) -> str:
    match = re.search(r"(/dev/nvme\S+)", query)
    if match:
        return match.group(1).strip()
    return ""


def _should_background(query: str) -> bool:
    lower = query.lower()
    return any(term in lower for term in ("background", "async", "behind", "in background"))




def _extract_firmware_version(query: str) -> str:
    match = re.search(r"\b(?:version|ver|v)\s*([A-Za-z0-9_.-]+)\b", query, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"\b([0-9]{3}[A-Za-z0-9]+)\b", query)
    if match:
        return match.group(1).strip()
    return ""


def _parse_test_status_query(query: str) -> Tuple[str, str, str]:
    """Return (action, case_id, host) for /test commands."""

    parts = query.strip().split()
    if not parts or parts[0].lower() not in {"/test", "/testcase"}:
        return "", "", ""
    action = parts[1].lower() if len(parts) > 1 else "status"
    case_id = ""
    host = ""
    for token in parts[2:]:
        if re.match(r"^(TC|DSSTC)-\d+", token, re.IGNORECASE):
            case_id = token.upper()
        elif token.lower() not in {"on", "host"}:
            host = token
    return action, case_id, host


def _resolve_host_address(host: str, cfg_path: str) -> Tuple[str, str]:
    """Return (address, resolved_name)."""

    resolved = _resolve_host_config(load_ssh_config(cfg_path), host)
    return resolved.get("address", ""), resolved.get("resolved_hostname", "") or host


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_junit_report(
    path: Path,
    case_id: str,
    host: str,
    status: str,
    duration_sec: float,
    error_message: str = "",
) -> None:
    import xml.etree.ElementTree as ET

    testsuite = ET.Element("testsuite", {
        "name": f"SENA {case_id}",
        "tests": "1",
        "failures": "1" if status == "fail" else "0",
        "errors": "1" if status == "error" else "0",
        "time": f"{duration_sec:.2f}",
    })
    testcase = ET.SubElement(testsuite, "testcase", {
        "classname": "SENA.Testcase",
        "name": case_id,
        "time": f"{duration_sec:.2f}",
    })
    if status in {"fail", "error"}:
        failure = ET.SubElement(testcase, "failure", {
            "message": error_message or status,
            "type": status,
        })
        failure.text = error_message or status
    system_out = ET.SubElement(testcase, "system-out")
    system_out.text = f"Host: {host}"
    tree = ET.ElementTree(testsuite)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)




def _collect_logs(host: str, cfg_path: str, timeout_sec: int) -> Dict[str, str]:
    """Collect standard logs from the host."""

    commands = {
        "dmesg.log": "sudo -n dmesg -T --level=err,crit,alert,emerg | tail -n 200",
        "journal.log": "sudo -n journalctl -k -p 3 -b --no-pager | tail -n 200",
        "lspci.log": "sudo -n lspci -vv | head -n 200",
        "nvme_list.log": "sudo -n nvme list",
        "nvme_smart.log": "sudo -n nvme smart-log /dev/nvme0",
        "nvme_error.log": "sudo -n nvme error-log /dev/nvme0",
    }
    outputs: Dict[str, str] = {}
    for name, command in commands.items():
        _ensure_allowlist(command.replace("sudo -n ", ""), cfg_path)
        try:
            result = run_ssh_command(host, command, cfg_path, timeout_sec=timeout_sec)
            if result.success:
                outputs[name] = result.stdout
            else:
                outputs[name] = f"[ERROR] {result.stderr or 'command failed'}"
        except Exception as exc:
            outputs[name] = f"[ERROR] {exc}"
    return outputs


def _bundle_artifacts(artifact_dir: Path, bundle_name: str) -> Path:
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = BUNDLES_DIR / f"{bundle_name}.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(artifact_dir, arcname=artifact_dir.name)
    return bundle_path


def _build_system_info(hosts: List[dict], cfg_path: str, output_path: Path) -> None:
    cfg = load_ssh_config(cfg_path)
    default_user = cfg.get("default_user", "")
    default_password = cfg.get("default_password", "")
    system_info = []
    for record in hosts:
        ip = record.get("address") or ""
        hostname = record.get("hostname") or ""
        if not ip:
            continue
        system_info.append(
            {
                "ip": ip,
                "username": default_user,
                "password": default_password,
                "hostname": hostname,
                "is_windows": False,
            }
        )
    output_path.write_text(json.dumps(system_info, indent=2), encoding="utf-8")


def _run_firmware_update(query: str) -> str:
    cfg = load_config()
    version = _extract_firmware_version(query)
    if not version:
        return "Missing firmware version. Example: Update firmware version 007S on rack D1"

    rack = _extract_rack(query)
    host = _extract_host(query)
    hosts: List[dict] = []
    if rack:
        hosts = _fetch_hosts_by_rack(rack, cfg)
    elif host:
        address, resolved_name = _resolve_host_address(host, cfg.ssh_config_path)
        hosts = [{"address": address, "hostname": resolved_name}]

    if not hosts:
        return "No hosts resolved for firmware update. Provide a host or rack."

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = EXPORTS_DIR / f"firmware_{version}_{timestamp}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    system_info_path = artifact_dir / "system_info.json"
    connectivity = [check_connectivity(h.get("address") or h.get("hostname") or "", cfg.ssh_config_path) for h in hosts]
    _write_text(artifact_dir / "connectivity.json", json.dumps(connectivity, indent=2))
    reachable = [h for h, c in zip(hosts, connectivity) if c.get("port_open")]
    if not reachable:
        bundle = _bundle_artifacts(artifact_dir, f"firmware_{version}_{timestamp}")
        return "No reachable hosts for firmware update.\n" f"Bundle saved: {bundle}"
    _build_system_info(reachable, cfg.ssh_config_path, system_info_path)

    dry_run = True
    if any(word in query.lower() for word in ("execute", "apply", "run update", "perform update")):
        dry_run = False

    cmd = [
        sys.executable,
        str(FIRMWARE_DIR / "speed.py"),
        "-v",
        version,
        "--system_info",
        str(system_info_path),
        "--dry-run" if dry_run else "--verbose",
    ]

    result_text = f"Command: {' '.join(cmd)}\n"
    try:
        import subprocess

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        result_text += f"Exit code: {proc.returncode}\n\nSTDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
    except Exception as exc:
        result_text += f"Execution failed: {exc}"

    _write_text(artifact_dir / "firmware_update.log", result_text)
    bundle = _bundle_artifacts(artifact_dir, f"firmware_{version}_{timestamp}")
    return (
        f"Firmware update {'dry-run' if dry_run else 'run'} complete.\n"
        f"Bundle saved: {bundle}"
    )


def _execute_testcase_run(
    *,
    cfg,
    case_id: str,
    host: str,
    script,
    device: str,
    run_id: str,
    artifact_dir: Path,
    session_id: str | None,
) -> str:
    """Execute a testcase run and return the response text."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    remote_dir = f"/tmp/sena_tools/{case_id}"
    remote_script = f"{remote_dir}/{script.path.name}"
    reporter = get_reporter()
    reporter.report_test_started(case_id=case_id, host=host, session_id=session_id or "")
    try:
        upload_file(host, script.path, remote_script, cfg.ssh_config_path, timeout_sec=cfg.request_timeout_sec)
        msecli_path = script.path.parent / "msecli"
        if msecli_path.exists():
            upload_file(host, msecli_path, f"{remote_dir}/msecli", cfg.ssh_config_path, timeout_sec=cfg.request_timeout_sec)

        connectivity = check_connectivity(host, cfg.ssh_config_path)
        _write_text(artifact_dir / "connectivity.json", json.dumps(connectivity, indent=2))
        if not connectivity.get("port_open"):
            analysis = analyze_logs(
                logs={},
                testcase_id=case_id,
                host=host,
                status="skipped",
                base_url=cfg.ollama_base_url,
                model=cfg.chat_model,
                timeout_sec=cfg.request_timeout_sec,
                facts={"connectivity": connectivity},
            )
            _write_text(artifact_dir / "analysis.md", analysis)
            bundle = _bundle_artifacts(artifact_dir, f"run_{case_id}_{host}_{timestamp}")
            summary = f"Testcase {case_id} skipped (connectivity failure)."
            update_run(
                STATUS_PATH,
                run_id,
                {
                    "status": "skipped",
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "bundle_path": str(bundle),
                    "summary": summary,
                },
            )
            reporter.report_test_completed(
                case_id=case_id,
                status="skipped",
                host=host,
                duration_sec=0.0,
                error_message="connectivity failure",
                session_id=session_id or "",
                artifacts=[str(bundle)],
            )
            return (
                f"{summary}\n"
                f"Analysis:\n{analysis}\n\n"
                f"Bundle saved: {bundle}"
            )

        if script.requires_device and not device:
            try:
                nvme_result = run_ssh_command(host, "sudo -n nvme list", cfg.ssh_config_path)
                if nvme_result.success:
                    nvme_list = nvme_result.stdout
                else:
                    nvme_list = ""
                match = re.search(r"(/dev/nvme\\S+)", nvme_list)
                if match:
                    device = match.group(1)
            except Exception:
                device = ""

        if script.requires_device and not device:
            summary = f"Testcase {case_id} skipped (missing NVMe device)."
            _write_text(artifact_dir / "analysis.md", summary)
            bundle = _bundle_artifacts(artifact_dir, f"run_{case_id}_{host}_{timestamp}")
            update_run(
                STATUS_PATH,
                run_id,
                {
                    "status": "skipped",
                    "ended_at": datetime.now(timezone.utc).isoformat(),
                    "bundle_path": str(bundle),
                    "summary": summary,
                },
            )
            reporter.report_test_completed(
                case_id=case_id,
                status="skipped",
                host=host,
                duration_sec=0.0,
                error_message="missing NVMe device",
                session_id=session_id or "",
                artifacts=[str(bundle)],
            )
            return f"{summary}\nBundle saved: {bundle}"

        command_parts = ["python3", remote_script]
        if case_id == "TC-3362":
            command_parts += ["--log-folder", remote_dir]
        if script.requires_device:
            command_parts += ["--device", device, "--execute"]

        command = " ".join(command_parts)
        _ensure_allowlist(command, cfg.ssh_config_path)

        result = run_ssh_command_with_status(
            host,
            command,
            cfg.ssh_config_path,
            timeout_sec=cfg.request_timeout_sec,
        )
        stdout = result.stdout
        stderr = result.stderr
        rc = result.exit_code or 1
        duration_sec = result.duration_sec or 0.0

        _write_text(artifact_dir / "testcase_stdout.log", stdout)
        _write_text(artifact_dir / "testcase_stderr.log", stderr)
        _write_text(artifact_dir / "testcase_command.txt", command)

        status = "pass" if rc == 0 else "fail"
        logs = _collect_logs(host, cfg.ssh_config_path, cfg.request_timeout_sec)
        for name, content in logs.items():
            _write_text(artifact_dir / name, content)
            signals = normalize_telemetry(name, content)
            if signals:
                store_evidence_event(
                    session_id=session_id,
                    host=host,
                    source=name,
                    signals=signals,
                    raw_excerpt=content[:4000],
                )

        facts = parse_logs(logs)
        _write_text(artifact_dir / "facts.json", json.dumps(facts, indent=2))
        citations = build_citations(facts)
        _write_text(artifact_dir / "citations.md", citations)

        testcase_record = load_testcase(case_id)
        audit_summary = ""
        if testcase_record:
            error_count = sum(facts.get("counts", {}).values()) if isinstance(facts, dict) else 0
            audit = audit_testcase(testcase_record, logs, status, error_count)
            audit_summary = format_audit_markdown(audit)
            _write_text(artifact_dir / "audit.json", json.dumps(audit, indent=2))
            _write_text(artifact_dir / "audit.md", audit_summary)

        analysis = analyze_logs(
            logs={**logs, "testcase_stdout": stdout, "testcase_stderr": stderr},
            testcase_id=case_id,
            host=host,
            status=status,
            base_url=cfg.ollama_base_url,
            model=cfg.chat_model,
            timeout_sec=cfg.request_timeout_sec,
            facts=facts,
            citations=citations,
        )
        _write_text(artifact_dir / "analysis.md", analysis)

        bundle = _bundle_artifacts(artifact_dir, f"run_{case_id}_{host}_{timestamp}")
        summary = f"Testcase {case_id} complete on {host} (status: {status})."
        trace_req = get_requirement_for_test(case_id)
        trace_info: Dict[str, object] = {}
        if trace_req:
            trace_info = {
                "requirement_id": trace_req.id,
                "source_document": trace_req.source_document,
                "section": trace_req.section,
                "description": trace_req.description,
            }

        junit_path = artifact_dir / "junit_report.xml"
        _write_junit_report(
            junit_path,
            case_id=case_id,
            host=host,
            status=status,
            duration_sec=duration_sec,
            error_message=stderr if status != "pass" else "",
        )
        json_report = {
            "case_id": case_id,
            "host": host,
            "status": status,
            "duration_sec": duration_sec,
            "command": command,
            "traceability": trace_info,
            "artifacts": {
                "bundle": str(bundle),
                "junit": str(junit_path),
                "stdout": str(artifact_dir / "testcase_stdout.log"),
                "stderr": str(artifact_dir / "testcase_stderr.log"),
            },
        }
        _write_json(artifact_dir / "testcase_result.json", json_report)

        reporter.report_test_completed(
            case_id=case_id,
            status=status,
            host=host,
            duration_sec=duration_sec,
            error_message=stderr if status != "pass" else "",
            output=stdout,
            artifacts=[str(bundle), str(junit_path)],
            session_id=session_id or "",
            metadata=trace_info,
        )
        update_run(
            STATUS_PATH,
            run_id,
            {
                "status": status,
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "bundle_path": str(bundle),
                "summary": summary,
            },
        )
        response = (
            f"{summary}\n"
            f"{audit_summary}\n\n"
            f"Analysis:\n{analysis}\n\n"
            f"Bundle saved: {bundle}"
        )
        if trace_req:
            response = enrich_test_result_with_trace(response, case_id)
        response += f"\nJUnit report: {junit_path}"
        return response
    except Exception as exc:
        _write_text(artifact_dir / "error.txt", str(exc))
        bundle = _bundle_artifacts(artifact_dir, f"run_{case_id}_{host}_{timestamp}")
        summary = f"Testcase {case_id} failed on {host}: {exc}"
        reporter.report_test_completed(
            case_id=case_id,
            status="fail",
            host=host,
            duration_sec=0.0,
            error_message=str(exc),
            session_id=session_id or "",
            artifacts=[str(bundle)],
        )
        update_run(
            STATUS_PATH,
            run_id,
            {
                "status": "fail",
                "ended_at": datetime.now(timezone.utc).isoformat(),
                "bundle_path": str(bundle),
                "summary": summary,
            },
        )
        return f"{summary}\nBundle saved: {bundle}"


def _run_testcase_pipeline(query: str, session_id: str | None, background: bool = False) -> str:
    cfg = load_config()
    case_id = _extract_case_id(query)
    if not case_id:
        available = ", ".join(list_testcase_ids(TESTCASE_DIR))
        return f"Missing testcase ID. Available: {available}"
    script = resolve_testcase_script(TESTCASE_DIR, case_id)
    if not script:
        available = ", ".join(list_testcase_ids(TESTCASE_DIR))
        return f"Testcase script not found for {case_id}. Available: {available}"

    host = _extract_host(query)
    if not host:
        return f"Missing host/service tag. Example: Run testcase {case_id} on host 98HLZ85"

    device = _extract_device(query)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = EXPORTS_DIR / f"run_{case_id}_{host}_{timestamp}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{case_id}_{host}_{timestamp}"
    append_run(
        STATUS_PATH,
        {
            "run_id": run_id,
            "session_id": session_id or "",
            "case_id": case_id,
            "host": host,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "log_dir": str(artifact_dir),
            "bundle_path": "",
        },
    )

    if background:
        thread = threading.Thread(
            target=_execute_testcase_run,
            kwargs={
                "cfg": cfg,
                "case_id": case_id,
                "host": host,
                "script": script,
                "device": device,
                "run_id": run_id,
                "artifact_dir": artifact_dir,
                "session_id": session_id,
            },
            daemon=True,
        )
        thread.start()
        return (
            f"Testcase {case_id} started in background on {host}.\n"
            f"Check status with: /test status {case_id} {host}"
        )

    return _execute_testcase_run(
        cfg=cfg,
        case_id=case_id,
        host=host,
        script=script,
        device=device,
        run_id=run_id,
        artifact_dir=artifact_dir,
        session_id=session_id,
    )




def orchestrator_node(state: GraphState | dict) -> dict:
    """Entry point for multi-step tool orchestration."""

    current = coerce_state(state)
    query = current.augmented_query or current.query

    lowered = query.lower()
    natural_case = _extract_case_id(query)
    natural_host = _extract_host(query)
    if ("status" in lowered and ("testcase" in lowered or "test case" in lowered)) or lowered.startswith("testcase status"):
        run = latest_run(STATUS_PATH, case_id=natural_case or None, host=natural_host or None, session_id=current.session_id)
        if not run:
            current.response = "No matching testcase runs found."
        else:
            current.response = format_status(run)
        return state_to_dict(current)
    if "log" in lowered and ("testcase" in lowered or "test case" in lowered):
        run = latest_run(STATUS_PATH, case_id=natural_case or None, host=natural_host or None, session_id=current.session_id)
        if not run:
            current.response = "No matching testcase runs found."
        else:
            current.response = (
                f"Log directory: {run.get('log_dir', '')}\n"
                f"Bundle: {run.get('bundle_path', '')}"
            )
        return state_to_dict(current)

    action, case_id, host = _parse_test_status_query(query)
    if action:
        run = latest_run(STATUS_PATH, case_id=case_id or None, host=host or None, session_id=current.session_id)
        if not run:
            current.response = "No matching testcase runs found."
            return state_to_dict(current)
        if action in {"status", "state"}:
            current.response = format_status(run)
            return state_to_dict(current)
        if action in {"log", "logs"}:
            current.response = (
                f"Log directory: {run.get('log_dir', '')}\n"
                f"Bundle: {run.get('bundle_path', '')}"
            )
            return state_to_dict(current)

    if "audit" in lowered:
        current.response = run_audit_pipeline(query)
        return state_to_dict(current)

    case_id = _extract_case_id(query)
    if case_id:
        background = _should_background(query)
        current.response = _run_testcase_pipeline(query, current.session_id, background=background)
        return state_to_dict(current)

    if "firmware" in query.lower() and ("update" in query.lower() or query.lower().startswith("/fw")):
        current.response = _run_firmware_update(query)
        return state_to_dict(current)

    current.response = (
        "Usage:\n"
        "- Run testcase TC-3362 on host 98HLZ85 (add 'background' to run async)\n"
        "- Run testcase DSSTC-5351 on host 98HLZ85 device /dev/nvme0n1\n"
        "- Audit testcase TC-15174 log path /path/to/logs\n"
        "- Update firmware version 007S on rack D1 (dry-run by default)"
    )
    return state_to_dict(current)
