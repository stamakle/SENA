"""Testcase script registry for custom tool execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TestcaseScript:
    case_id: str
    path: Path
    requires_device: bool = False


def _script_case_id(name: str) -> Optional[str]:
    match = re.search(r"(DSSTC-\d+)", name, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    match = re.search(r"(?<!DS)(TC-\d+)", name, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def load_testcase_scripts(base_dir: Path) -> Dict[str, TestcaseScript]:
    """Scan testcase script directory and return mapping."""

    scripts: Dict[str, TestcaseScript] = {}
    if not base_dir.exists():
        return scripts
    for path in sorted(base_dir.glob("*.py")):
        if path.name.endswith(":Zone.Identifier"):
            continue
        case_id = _script_case_id(path.name)
        if not case_id:
            continue
        requires_device = "fio" in path.name.lower()
        scripts[case_id] = TestcaseScript(case_id=case_id, path=path, requires_device=requires_device)
    return scripts


def list_testcase_ids(base_dir: Path) -> List[str]:
    """Return list of available testcase IDs."""

    return sorted(load_testcase_scripts(base_dir).keys())


def resolve_testcase_script(base_dir: Path, case_id: str) -> Optional[TestcaseScript]:
    """Resolve a testcase ID to a script."""

    scripts = load_testcase_scripts(base_dir)
    return scripts.get(case_id.upper())
