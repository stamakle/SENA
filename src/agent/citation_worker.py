"""Citation worker for linking analysis to log evidence."""

from __future__ import annotations

from typing import Dict, List


def build_citations(facts: Dict[str, object]) -> str:
    """Build a markdown citation list from parsed facts."""

    evidence = facts.get("evidence", {}) if isinstance(facts, dict) else {}
    lines: List[str] = ["## Evidence Citations"]
    for category, items in evidence.items():
        if not items:
            continue
        lines.append(f"\n### {category.capitalize()}")
        for item in items:
            file = item.get("file", "")
            line_no = item.get("line", "")
            text = item.get("text", "")
            lines.append(f"- {file}:{line_no} — {text}")
    if len(lines) == 1:
        return "## Evidence Citations\n- No evidence lines detected."
    return "\n".join(lines)
