"""Audit pipeline for testcase logs and post-run analysis."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

from src.config import load_config
from src.agent.debug_agent import analyze_logs
from src.agent.log_parser import parse_logs
from src.agent.citation_worker import build_citations
from src.agent.testcase_auditor import load_testcase, audit_testcase, format_audit_markdown
from src.agent.model_router import select_chat_model


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORTS_DIR = PROJECT_ROOT / "data" / "exports"
BUNDLES_DIR = EXPORTS_DIR / "bundles"


def _extract_case_id(query: str) -> str:
    match = re.search(r"\b(?:TC|DSSTC)-\d+\b", query, re.IGNORECASE)
    return match.group(0).upper() if match else ""


def _extract_host(query: str) -> str:
    match = re.search(
        r"(?:hostname|host|server|system)\s*[:#]?\s*([\w.-]+)",
        query,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match = re.search(r"\bon\s+([\w.-]+)", query, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _parse_audit_request(query: str) -> Tuple[str, str]:
    lower = query.lower()
    if "audit" not in lower:
        return "", ""
    case_id = _extract_case_id(query)
    path = ""
    match = re.search(r"(?:log\s*path|logfile|log\s*file|path)\s+([^\s]+)", query, re.IGNORECASE)
    if match:
        path = match.group(1).strip().strip("\"'.,;")
    if not path:
        for token in query.split():
            if "/" in token:
                path = token.strip().strip("\"'.,;")
                break
    return case_id, path


def _load_logs_from_path(log_path: Path, max_bytes: int = 2_000_000) -> Dict[str, str]:
    """Load log text files from a directory or file."""

    logs: Dict[str, str] = {}
    if log_path.is_file():
        try:
            data = log_path.read_text(encoding="utf-8", errors="replace")
            logs[log_path.name] = data[:max_bytes]
        except Exception as exc:
            logs[log_path.name] = f"[ERROR] {exc}"
        return logs

    if log_path.is_dir():
        for item in sorted(log_path.iterdir()):
            if not item.is_file():
                continue
            if item.suffix.lower() not in {".log", ".txt", ".out", ".err", ".md"}:
                continue
            try:
                data = item.read_text(encoding="utf-8", errors="replace")
                logs[item.name] = data[:max_bytes]
            except Exception as exc:
                logs[item.name] = f"[ERROR] {exc}"
    return logs


def _bundle_artifacts(artifact_dir: Path, bundle_name: str) -> Path:
    import tarfile

    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = BUNDLES_DIR / f"{bundle_name}.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as tar:
        tar.add(artifact_dir, arcname=artifact_dir.name)
    return bundle_path


def run_audit_pipeline(query: str) -> str:
    """Run audit on a testcase log path and return a response."""

    cfg = load_config()
    case_id, log_path_raw = _parse_audit_request(query)
    if not case_id:
        case_id = _extract_case_id(query)
    if not case_id:
        return "Missing testcase ID for audit. Example: Audit testcase TC-1234 log path /path/to/logs"
    if not log_path_raw:
        return "Missing log path. Example: Audit testcase TC-1234 log path /path/to/logs"

    log_path = Path(log_path_raw).expanduser()
    if not log_path.is_absolute():
        log_path = (PROJECT_ROOT / log_path).resolve()
    if not log_path.exists():
        return f"Log path not found: {log_path}"

    testcase_record = load_testcase(case_id)
    if not testcase_record:
        return f"Testcase {case_id} not found in the database."

    logs = _load_logs_from_path(log_path)
    if not logs:
        return f"No log files found at {log_path}"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = EXPORTS_DIR / f"audit_{case_id}_{timestamp}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_dir = artifact_dir / "inputs"
    for name, content in logs.items():
        input_dir.mkdir(parents=True, exist_ok=True)
        (input_dir / name).write_text(content, encoding="utf-8")

    facts = parse_logs(logs)
    (artifact_dir / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    citations = build_citations(facts)
    (artifact_dir / "citations.md").write_text(citations, encoding="utf-8")
    error_count = sum(facts.get("counts", {}).values()) if isinstance(facts, dict) else 0
    audit = audit_testcase(testcase_record, logs, "audit", error_count)
    audit_summary = format_audit_markdown(audit)
    audit_md = artifact_dir / "audit.md"
    audit_md.write_text(audit_summary, encoding="utf-8")
    (artifact_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")

    model = select_chat_model(query, True, cfg)
    analysis = analyze_logs(
        logs=logs,
        testcase_id=case_id,
        host=_extract_host(query) or "local",
        status="audit",
        base_url=cfg.ollama_base_url,
        model=model,
        timeout_sec=cfg.request_timeout_sec,
        facts=facts,
        citations=citations,
    )
    (artifact_dir / "analysis.md").write_text(analysis, encoding="utf-8")

    bundle = _bundle_artifacts(artifact_dir, f"audit_{case_id}_{timestamp}")
    return (
        f"Audit complete for {case_id}.\n"
        f"Audit saved: {audit_md}\n\n"
        f"Analysis:\n{analysis}\n\n"
        f"Bundle saved: {bundle}"
    )
