"""Debug analysis helper for log bundles."""

from __future__ import annotations

from typing import Dict

from src.llm.ollama_client import chat_completion


def analyze_logs(
    logs: Dict[str, str],
    testcase_id: str,
    host: str,
    status: str,
    base_url: str,
    model: str,
    timeout_sec: int,
    max_chars: int = 6000,
    facts: Dict[str, object] | None = None,
    citations: str | None = None,
) -> str:
    """Generate a critical analysis and suggested actions."""

    def _truncate(value: str) -> str:
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + "\n...[truncated]"

    summary_sections = []
    for name, content in logs.items():
        if not content:
            continue
        summary_sections.append(f"## {name}\n{_truncate(content)}")

    facts_block = ""
    if facts:
        facts_block = f"Structured facts (JSON):\n{facts}\n\n"
    citations_block = ""
    if citations:
        citations_block = f"{citations}\n\n"

    user_prompt = (
        f"Testcase: {testcase_id}\n"
        f"Host: {host}\n"
        f"Status: {status}\n\n"
        f"{facts_block}"
        f"{citations_block}"
        "You are a debug analyst. Analyze the logs below and provide:\n"
        "1) Critical issues found\n"
        "2) Likely root cause(s)\n"
        "3) Suggested next steps or fixes\n"
        "4) Any missing data to confirm the diagnosis\n\n"
        + "\n\n".join(summary_sections)
    )

    system_prompt = (
        "You are a senior SSD validation engineer. Be concise, technical, and actionable. "
        "If logs are inconclusive, say so clearly."
    )

    return chat_completion(
        base_url=base_url,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        timeout_sec=timeout_sec,
        num_predict=512,
    )
