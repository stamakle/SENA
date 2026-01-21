"""Prepare raw CSV/TSV files into JSONL for indexing.

This script reads the raw dataset, normalizes fields, groups test steps, and
writes clean JSONL outputs for downstream indexing.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List


# Step 2: Prepare the data.


def _read_tabular(path: Path) -> List[Dict[str, str]]:
    """Load a CSV or TSV file into a list of dictionaries.

    This tries UTF-8 first and falls back to Windows-1252 for legacy exports.
    """

    suffix = path.suffix.lower()
    delimiter = "\t" if suffix in {".tsv", ".txt"} else ","
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            return [row for row in reader]
    except UnicodeDecodeError:
        with path.open("r", encoding="cp1252", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            return [row for row in reader]


def _normalize_header(header: str) -> str:
    """Normalize a header name for consistent field access."""

    return re.sub(r"\s+", " ", header.strip().lower())


def _normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    """Normalize a row by lowercasing keys and stripping values."""

    normalized: Dict[str, str] = {}
    for key, value in row.items():
        if key is None:
            continue
        normalized[_normalize_header(key)] = (value or "").strip()
    return normalized


def _extract_case_id(row: Dict[str, str]) -> str:
    """Extract a stable test case ID from a row if possible."""

    for field in (
        "test_case",
        "id",
        "test case entity key (qmetry)",
        "test case",
    ):
        value = row.get(field)
        if value:
            return value
    return ""


def _build_test_cases(rows: Iterable[Dict[str, str]]) -> List[Dict[str, object]]:
    """Group test case rows into case-level records with ordered steps."""

    grouped: Dict[str, Dict[str, object]] = {}
    steps_by_case: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for raw in rows:
        row = _normalize_row(raw)
        case_id = _extract_case_id(row) or f"case-{len(grouped) + 1}"
        if case_id not in grouped:
            grouped[case_id] = {
                "case_id": case_id,
                "name": row.get("name", ""),
                "status": row.get("status", ""),
                "type": row.get("type", ""),
                "description": row.get("description", ""),
                "precondition": row.get("precondition", ""),
                "steps": [],
                "source": row.get("test group", ""),
            }
        step_number = row.get("test step #") or row.get("test step") or ""
        step_description = row.get("test step description", "")
        step_expected = row.get("test step expected result", "")
        if step_number or step_description or step_expected:
            steps_by_case[case_id].append(
                {
                    "step": step_number,
                    "description": step_description,
                    "expected": step_expected,
                }
            )

    for case_id, record in grouped.items():
        record["steps"] = steps_by_case.get(case_id, [])

    return list(grouped.values())


def _build_system_logs(rows: Iterable[Dict[str, str]]) -> List[Dict[str, object]]:
    """Normalize system log rows into host-level records."""

    records: List[Dict[str, object]] = []
    for idx, raw in enumerate(rows, start=1):
        row = _normalize_row(raw)
        system_id = row.get("service tag") or row.get("hostname") or f"system-{idx}"
        records.append(
            {
                "system_id": system_id,
                "hostname": row.get("hostname", ""),
                "model": row.get("model", ""),
                "rack": row.get("rack", ""),
                "metadata": row,
            }
        )
    return records


def _write_jsonl(records: Iterable[Dict[str, object]], output_path: Path) -> None:
    """Write records to a JSONL file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def prepare_data(input_dir: Path, output_dir: Path) -> None:
    """Main entry point for preparing both test cases and system logs."""

    test_case_paths = sorted((input_dir / "test_cases").glob("*.csv"))
    system_log_paths = sorted((input_dir / "system_logs").glob("*"))

    test_rows: List[Dict[str, str]] = []
    for path in test_case_paths:
        test_rows.extend(_read_tabular(path))

    system_rows: List[Dict[str, str]] = []
    for path in system_log_paths:
        if path.is_file() and path.suffix.lower() in {".csv", ".tsv", ".txt"}:
            system_rows.extend(_read_tabular(path))

    test_cases = _build_test_cases(test_rows)
    system_logs = _build_system_logs(system_rows)

    _write_jsonl(test_cases, output_dir / "test_cases.jsonl")
    _write_jsonl(system_logs, output_dir / "system_logs.jsonl")


def main() -> None:
    """CLI wrapper for preparing data from the dataset directory."""

    parser = argparse.ArgumentParser(description="Prepare RAG data into JSONL.")
    parser.add_argument("--input-dir", required=True, help="Path to raw data directory")
    parser.add_argument("--output-dir", required=True, help="Path to output directory")
    args = parser.parse_args()

    prepare_data(Path(args.input_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()
