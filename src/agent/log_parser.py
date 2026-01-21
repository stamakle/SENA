"""Structured log parser worker for deterministic facts."""

from __future__ import annotations

import re
from typing import Dict, List


_CATEGORIES = {
    "errors": [r"\berror\b", r"\bfailed\b", r"\bfailure\b", r"\bpanic\b"],
    "warnings": [r"\bwarn\b", r"\bwarning\b", r"\bdeprecated\b"],
    "timeouts": [r"\btimeout\b", r"timed out"],
    "resets": [r"\breset\b", r"\breinit", r"\brecover"],
    "nvme": [r"\bnvme\b", r"\bblk\b", r"\bio error\b"],
    "aer": [r"\baer\b", r"\bpcie\b", r"\bpcie bus error\b"],
    "link": [r"link is down", r"link is up"],
    "apparmor": [r"apparmor", r"denied"],
}


def _compile_patterns() -> Dict[str, List[re.Pattern]]:
    compiled: Dict[str, List[re.Pattern]] = {}
    for key, patterns in _CATEGORIES.items():
        compiled[key] = [re.compile(pat, re.IGNORECASE) for pat in patterns]
    return compiled


_PATTERNS = _compile_patterns()


def parse_logs(logs: Dict[str, str], max_evidence: int = 5) -> Dict[str, object]:
    """Parse logs into structured facts and evidence snippets."""

    facts = {
        "counts": {key: 0 for key in _CATEGORIES.keys()},
        "evidence": {key: [] for key in _CATEGORIES.keys()},
        "files": {},
    }

    for filename, content in logs.items():
        if content is None:
            continue
        lines = content.splitlines()
        facts["files"][filename] = len(lines)
        for idx, line in enumerate(lines, start=1):
            for category, patterns in _PATTERNS.items():
                if facts["counts"][category] and len(facts["evidence"][category]) >= max_evidence:
                    continue
                if any(pattern.search(line) for pattern in patterns):
                    facts["counts"][category] += 1
                    if len(facts["evidence"][category]) < max_evidence:
                        facts["evidence"][category].append(
                            {
                                "file": filename,
                                "line": idx,
                                "text": line.strip(),
                            }
                        )
    return facts
