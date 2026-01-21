"""Query parsing helpers for simple intent and filter extraction.

This module adds a beginner-friendly layer to route queries and extract
obvious filters like rack or test case IDs.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple


# Step 6: Create the retrieval function (routing and filters).

FOLLOW_UP_PREFIXES = ("yes", "please", "outline", "more", "continue", "ok")


def _last_user_message(history: List[Dict[str, str]] | None) -> str:
    """Return the most recent user message from history."""

    if not history:
        return ""
    for item in reversed(history):
        if item.get("role") == "user" and item.get("content"):
            return item["content"].strip()
    return ""


def augment_query(query: str, history: List[Dict[str, str]] | None) -> str:
    """Augment short follow-ups with the last user question."""

    cleaned = query.strip()
    if not cleaned:
        return cleaned
    cleaned = re.sub(r"\bsytem\b", "system", cleaned, flags=re.IGNORECASE)
    lower = cleaned.lower()
    is_short = len(lower.split()) <= 4
    is_follow_up = is_short or lower.startswith(FOLLOW_UP_PREFIXES)
    if not is_follow_up:
        return cleaned
    last_user = _last_user_message(history)
    if not last_user or last_user.lower() == lower:
        return cleaned
    return f"{last_user}\nFollow-up: {cleaned}"


def extract_filters(query: str) -> Dict[str, str]:
    """Extract simple filters (rack, case_id, model, hostname, system_id) from the query."""

    filters: Dict[str, str] = {}
    rack_match = re.search(r"rack\s*([A-Za-z]\d+)", query, re.IGNORECASE)
    if rack_match:
        filters["rack"] = rack_match.group(1).upper()

    case_match = re.search(r"(TC-\d+)", query, re.IGNORECASE)
    if case_match:
        filters["case_id"] = case_match.group(1).upper()

    host_match = re.search(r"hostname\s*([\w.-]+)", query, re.IGNORECASE)
    if host_match:
        filters["hostname"] = host_match.group(1)

    service_tag_match = re.search(
        r"(?:service\s*tag|service[-_]?tag|system\s*id|system_id)\s*[:#]?\s*([\w.-]+)",
        query,
        re.IGNORECASE,
    )
    if service_tag_match:
        filters["system_id"] = service_tag_match.group(1)

    model_match = re.search(r"model\s*([\w.-]+)", query, re.IGNORECASE)
    if model_match:
        filters["model"] = model_match.group(1)

    return filters


def choose_tables(query: str, filters: Dict[str, str]) -> List[str]:
    """Pick target tables based on query keywords and filters."""

    lower = query.lower()
    system_terms = (
        "rack",
        "host",
        "hostname",
        "system",
        "server",
        "idrac",
        "bmc",
        "service tag",
        "service_tag",
        "servicetag",
        "system id",
        "system_id",
    )
    test_terms = ("test", "case", "step", "steps", "procedure", "spdm", "pcie", "ssd", "nvme")

    wants_system = any(term in lower for term in system_terms) or "rack" in filters
    wants_test = any(term in lower for term in test_terms) or "case_id" in filters

    if wants_system and not wants_test:
        return ["system_logs"]
    if wants_test and not wants_system:
        return ["test_cases"]
    return ["test_cases", "system_logs"]


def detect_step_mode(query: str) -> str:
    """Return the step detail mode: summary, steps_only, or detailed."""

    lower = query.lower()
    if "walk me through" in lower or "explain" in lower:
        return "detailed"
    if "expected result" in lower or "expected" in lower:
        return "detailed"
    if "detail" in lower or "detailed" in lower or "full steps" in lower:
        return "detailed"
    if "steps only" in lower or "only steps" in lower:
        return "steps_only"
    if "steps" in lower or "test step" in lower:
        return "steps_only"
    return "summary"


def parse_query(
    query: str, history: List[Dict[str, str]] | None
) -> Tuple[str, Dict[str, str], List[str], str]:
    """Return the augmented query, filters, target tables, and step mode."""

    augmented = augment_query(query, history)
    filters = extract_filters(augmented)
    tables = choose_tables(augmented, filters)
    step_mode = detect_step_mode(augmented)
    return augmented, filters, tables, step_mode
