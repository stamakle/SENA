"""Model routing heuristics for local LLM selection."""

from __future__ import annotations

import re

from src.config import Config


def select_chat_model(query: str, has_context: bool, cfg: Config) -> str:
    """Pick a chat model based on query complexity and context."""

    lower = query.lower()
    if re.search(r"\b(?:tc|dsstc)-\d+\b", lower):
        return cfg.chat_small_model
    if any(term in lower for term in ("summarize", "summary", "list", "show", "status")):
        return cfg.chat_small_model
    if len(query.split()) <= 4 and not has_context:
        return cfg.chat_small_model
    if any(term in lower for term in ("analyze", "root cause", "diagnose", "compare", "explain", "why", "how")):
        return cfg.chat_model
    if has_context and len(query) < 120:
        return cfg.chat_small_model
    return cfg.chat_model
