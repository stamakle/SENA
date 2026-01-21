"""Session summarization helper.

This module compresses a conversation history into a short summary for
follow-up questions.
"""

from __future__ import annotations

from typing import List, Dict

from src.llm.ollama_client import chat_completion


# Step 3: Session summary agent.


def summarize_history(
    history: List[Dict[str, str]],
    base_url: str,
    model: str,
    timeout_sec: int,
    max_tokens: int,
) -> str:
    """Summarize conversation history into short bullet points."""

    if not history:
        return ""

    lines = []
    for item in history[-12:]:
        role = item.get("role", "")
        content = item.get("content", "")
        if role and content:
            lines.append(f"{role}: {content}")

    system_prompt = (
        "You summarize SSD validation chats. Keep IDs, racks, and test case names. "
        "Highlight open questions."
    )
    user_prompt = (
        "Summarize this conversation into 4-6 bullet points. "
        "Keep it factual and short.\n\n"
        + "\n".join(lines)
    )
    return chat_completion(
        base_url,
        model,
        system_prompt,
        user_prompt,
        timeout_sec,
        num_predict=max_tokens,
    ).strip()
