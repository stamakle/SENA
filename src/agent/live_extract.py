"""Helpers to extract error-like lines from log output."""

from __future__ import annotations

import re
from typing import Iterable, List


# Step 16: Live output error extractor.


_ERROR_PATTERNS = [
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\bpanic\b", re.IGNORECASE),
    re.compile(r"\bdenied\b", re.IGNORECASE),
    re.compile(r"\baudit\b", re.IGNORECASE),
    re.compile(r"\bapparmor\b", re.IGNORECASE),
    re.compile(r"link is down", re.IGNORECASE),
    re.compile(r"\bcritical\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
    re.compile(r"\bsegfault\b", re.IGNORECASE),
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"hogged cpu", re.IGNORECASE),
    re.compile(r"interrupt took", re.IGNORECASE),
    re.compile(r"can't open", re.IGNORECASE),
    re.compile(r"no such file", re.IGNORECASE),
    re.compile(r"out of memory", re.IGNORECASE),
    re.compile(r"\boom\b", re.IGNORECASE),
    re.compile(r"soft lockup", re.IGNORECASE),
    re.compile(r"hard lockup", re.IGNORECASE),
    re.compile(r"\boops\b", re.IGNORECASE),
    re.compile(r"\bbug:\b", re.IGNORECASE),
    re.compile(r"call trace", re.IGNORECASE),
    re.compile(r"\btainted\b", re.IGNORECASE),
    re.compile(r"i/o error", re.IGNORECASE),
    re.compile(r"\bcorrupt\b", re.IGNORECASE),
]


def _matches_error(line: str) -> bool:
    """Return True when the line matches a generic error pattern."""

    return any(pattern.search(line) for pattern in _ERROR_PATTERNS)


def extract_error_lines(output: str, max_lines: int = 50) -> str:
    """Return a newline-separated list of error-like lines."""

    if not output.strip():
        return ""
    lines = output.splitlines()
    hits: List[str] = []
    for idx, line in enumerate(lines, start=1):
        if _matches_error(line):
            hits.append(f"{idx}: {line}")
        if len(hits) >= max_lines:
            break
    return "\n".join(hits)


def summarize_errors(output: str, max_lines: int = 8) -> str:
    """Return a short, deterministic summary of error-like lines."""

    extracted = extract_error_lines(output, max_lines=max_lines)
    if not extracted:
        return ""
    lines = extracted.splitlines()
    total = len(lines)
    preview = "\n".join(lines[:max_lines])
    return f"Found {total} error-like lines:\n{preview}"
