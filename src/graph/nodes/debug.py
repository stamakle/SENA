"""Debug node for analyzing live outputs or retrieved context."""

from __future__ import annotations

import os
from pathlib import Path

from src.agent.live_memory import get_live_entry
from src.agent.debug_agent import analyze_logs
from src.agent.log_parser import parse_logs
from src.agent.citation_worker import build_citations
from src.agent.model_router import select_chat_model
from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def debug_node(state: GraphState | dict) -> dict:
    """Analyze the latest live output or RAG context for issues."""

    current = coerce_state(state)
    cfg = load_config()
    query = current.augmented_query or current.query

    live_entry = get_live_entry(_live_path(), current.session_id) if current.session_id else None
    live_output = str(live_entry.get("output", "")).strip() if live_entry else ""
    host = str(live_entry.get("host", "")).strip() if live_entry else ""

    logs = {}
    if live_output:
        logs["live_output.log"] = live_output
    elif current.context:
        logs["context.txt"] = current.context

    if not logs:
        current.response = "No live output or context to debug. Run a live command or ask a RAG question first."
        return state_to_dict(current)

    facts = parse_logs(logs)
    citations = build_citations(facts)
    model = select_chat_model(query, bool(logs), cfg)
    analysis = analyze_logs(
        logs=logs,
        testcase_id="ad-hoc",
        host=host or "unknown",
        status="debug",
        base_url=cfg.ollama_base_url,
        model=model,
        timeout_sec=cfg.request_timeout_sec,
        facts=facts,
        citations=citations,
    )
    current.response = analysis
    return state_to_dict(current)
