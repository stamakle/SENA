"""Audit testcase execution logs against stored testcase steps."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.config import load_config
from src.db.postgres import get_connection


@dataclass
class TestcaseRecord:
    case_id: str
    name: str
    test_type: str
    steps: List[Dict[str, str]]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\\s/_-]+", " ", text.lower()).strip()


def _tokenize(text: str) -> List[str]:
    tokens = [t for t in _normalize(text).split() if len(t) > 3]
    return tokens


def _load_from_db(case_id: str) -> Optional[TestcaseRecord]:
    cfg = load_config()
    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id, name, type, steps FROM test_cases WHERE case_id = %s",
                (case_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return TestcaseRecord(
            case_id=row[0] or case_id,
            name=row[1] or "",
            test_type=row[2] or "",
            steps=row[3] or [],
        )
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _load_from_jsonl(case_id: str, path: Path) -> Optional[TestcaseRecord]:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        if str(record.get("case_id", "")).upper() == case_id.upper():
            return TestcaseRecord(
                case_id=record.get("case_id", case_id),
                name=record.get("name", ""),
                test_type=record.get("type", ""),
                steps=record.get("steps", []) or [],
            )
    return None


def load_testcase(case_id: str) -> Optional[TestcaseRecord]:
    record = _load_from_db(case_id)
    if record:
        return record
    fallback = Path(__file__).resolve().parents[2] / "data" / "processed" / "test_cases.jsonl"
    return _load_from_jsonl(case_id, fallback)


def _step_match_score(step_text: str, logs_text: str) -> float:
    tokens = _tokenize(step_text)
    if not tokens:
        return 0.0
    hits = sum(1 for tok in tokens if tok in logs_text)
    return hits / max(len(tokens), 1)


def audit_testcase(
    record: TestcaseRecord,
    logs: Dict[str, str],
    run_status: str,
    error_count: int,
    match_threshold: float = 0.25,
) -> Dict[str, object]:
    """Return an audit report for the testcase run."""

    combined_logs = "\n".join(logs.values()).lower()
    matches = []
    matched_steps = 0
    for step in record.steps:
        desc = step.get("description", "") or ""
        expected = step.get("expected", "") or ""
        step_text = f"{desc} {expected}".strip()
        score = _step_match_score(step_text, combined_logs)
        matched = score >= match_threshold
        if matched:
            matched_steps += 1
        matches.append(
            {
                "step": step.get("step", ""),
                "description": desc,
                "expected": expected,
                "match_score": round(score, 3),
                "matched": matched,
            }
        )

    total_steps = len(matches)
    match_ratio = matched_steps / max(total_steps, 1)
    if run_status == "pass" and error_count == 0 and match_ratio >= 0.6:
        audit_status = "pass"
    elif run_status == "fail" or error_count > 0:
        audit_status = "fail"
    else:
        audit_status = "inconclusive"

    return {
        "case_id": record.case_id,
        "name": record.name,
        "type": record.test_type,
        "run_status": run_status,
        "audit_status": audit_status,
        "match_ratio": round(match_ratio, 3),
        "matched_steps": matched_steps,
        "total_steps": total_steps,
        "matches": matches,
    }


def format_audit_markdown(audit: Dict[str, object]) -> str:
    """Render audit report as markdown."""

    lines = [
        "## Testcase Audit",
        f"- Case: {audit.get('case_id', '')}",
        f"- Name: {audit.get('name', '')}",
        f"- Type: {audit.get('type', '')}",
        f"- Run status: {audit.get('run_status', '')}",
        f"- Audit status: {audit.get('audit_status', '')}",
        f"- Match ratio: {audit.get('match_ratio', '')}",
        "",
        "| Step | Description | Expected | Match | Score |",
        "| --- | --- | --- | --- | --- |",
    ]
    for match in audit.get("matches", []):
        lines.append(
            "| {step} | {desc} | {exp} | {matched} | {score} |".format(
                step=match.get("step", ""),
                desc=str(match.get("description", "")).replace("|", "/"),
                exp=str(match.get("expected", "")).replace("|", "/"),
                matched="yes" if match.get("matched") else "no",
                score=match.get("match_score", ""),
            )
        )
    return "\n".join(lines)
