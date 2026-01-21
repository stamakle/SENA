"""Summarize node for live output or retrieved context."""

from __future__ import annotations

import os
from pathlib import Path

from src.agent.live_memory import get_live_entry
from src.agent.summary_live import summarize_live_output
from src.agent.summary_rag import summarize_context
from src.agent.session_memory import get_summary
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def _summary_path() -> Path:
    return Path(
        os.getenv(
            "SENA_SUMMARY_PATH",
            str(Path(__file__).resolve().parents[3] / "session_summaries.json"),
        )
    )


def summarize_node(state: GraphState | dict) -> dict:
    """Summarize live output, RAG context, or session summary."""

    current = coerce_state(state)
    query = current.augmented_query or current.query
    lower = query.lower()
    cfg = load_config()

    live_entry = get_live_entry(_live_path(), current.session_id) if current.session_id else None
    live_output = str(live_entry.get("output", "")).strip() if live_entry else ""
    context = current.context.strip() if current.context else ""

    wants_live = any(term in lower for term in ("live", "output", "log", "dmesg", "journal", "lspci", "nvme"))
    wants_context = any(term in lower for term in ("context", "rag", "evidence", "test case", "testcase"))

    if wants_live or (live_output and not context):
        if not live_output:
            current.response = "No live output available to summarize. Run a live command first."
        else:
            current.response = summarize_live_output(
                live_output,
                cfg.ollama_base_url,
                cfg.live_summary_model,
                cfg.request_timeout_sec,
                cfg.live_summary_max_tokens,
            )
        return state_to_dict(current)

    if wants_context or context:
        if not context:
            current.response = "No RAG context available to summarize."
        else:
            current.response = summarize_context(
                context,
                cfg.ollama_base_url,
                cfg.summary_model,
                cfg.request_timeout_sec,
                cfg.summary_max_tokens,
                cfg.summary_mode,
            )
        return state_to_dict(current)

    summary_entry = get_summary(_summary_path(), current.session_id) if current.session_id else None
    if summary_entry and summary_entry.get("summary"):
        current.response = str(summary_entry.get("summary"))
    else:
        current.response = "No summary data available yet. Ask a question or run a command first."
    return state_to_dict(current)
