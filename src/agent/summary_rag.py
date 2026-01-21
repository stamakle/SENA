"""RAG summary helper for compressing retrieved context.

This module creates a short summary of retrieved evidence so the main
response model sees a smaller, cleaner prompt.
"""

from __future__ import annotations

from typing import Optional

from src.llm.ollama_client import chat_completion


# Step 3: RAG Summary Agent.


def summarize_context(
    context: str,
    base_url: str,
    model: str,
    timeout_sec: int,
    max_tokens: int,
    mode: str,
) -> str:
    """Summarize retrieved context into a compact bullet list.

    Modes:
    - summary_only: return the summary bullets only
    - summary_with_evidence: return summary bullets + original evidence
    """

    if not context.strip():
        return ""

    system_prompt = (
        "You are a summarization assistant. Summarize the evidence without "
        "adding new facts. Keep it short and factual."
    )
    user_prompt = (
        "Summarize the following evidence into 5-8 short bullet points. "
        "Keep IDs, rack labels, and model names intact.\n\n"
        f"Evidence:\n{context}"
    )
    summary = chat_completion(
        base_url,
        model,
        system_prompt,
        user_prompt,
        timeout_sec,
        num_predict=max_tokens,
    ).strip()

    if mode == "summary_with_evidence":
        return f"{summary}\n\nEvidence:\n{context}".strip()
    return summary
