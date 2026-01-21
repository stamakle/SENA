"""Live RAG summary helper for SSH/tool outputs.

This module provides a compact summary of live command output for follow-ups.
"""

from __future__ import annotations

from src.llm.ollama_client import chat_completion


# Step 3: Live RAG Summary Agent.


def summarize_live_output(
    output: str,
    base_url: str,
    model: str,
    timeout_sec: int,
    max_tokens: int,
) -> str:
    """Summarize live tool output into a short, readable digest."""

    if not output.strip():
        return ""

    system_prompt = (
        "You summarize command output for SSD validation. Be concise and factual. "
        "Do not invent details or add assumptions. Use only evidence from the output."
    )
    user_prompt = (
        "Summarize the following command output into 3-6 short bullet points. "
        "Preserve key values like versions, IDs, and errors. "
        "If there are no issues, say \"No issues found in output.\".\n\n"
        f"Output:\n{output}"
    )
    return chat_completion(
        base_url,
        model,
        system_prompt,
        user_prompt,
        timeout_sec,
        num_predict=max_tokens,
    ).strip()
