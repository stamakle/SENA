"""Planner node for high-level SSD validation tasks."""

from __future__ import annotations


from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import chat_completion

def planner_node(state: GraphState | dict) -> dict:
    """Generate a high-level plan for the requested task using LLM."""
    current = coerce_state(state)
    query = current.augmented_query or current.query
    cfg = load_config()

    system_prompt = (
        "You are an Expert SSD Validation Planner.\n"
        "Create a concise, executable, step-by-step plan for the user's request.\n"
        "Focus on NVMe tools (nvme-cli), Linux commands, and validation best practices.\n"
        "Do not include conversational filler. Just the steps."
    )

    try:
        response = chat_completion(
            cfg.ollama_base_url,
            cfg.planner_model,
            system_prompt,
            f"User Request: {query}",
            cfg.request_timeout_sec,
        )
        current.plan = response
        current.response = f"**Proposed Plan:**\n{response}"
    except Exception as exc:
        current.error = f"Planner failed: {exc}"
        # Fallback
        current.response = f"Failed to generate plan. Error: {exc}"

    return state_to_dict(current)
