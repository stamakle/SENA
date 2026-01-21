"""Critic Node for Devil's Advocate Logic."""

from __future__ import annotations

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import chat_completion


# Step 1: Critique the plan before execution.

def critic_node(state: GraphState | dict) -> dict:
    """Critique the current plan and offer feedback/refinements."""
    current = coerce_state(state)
    cfg = load_config()

    if not current.plan:
        current.critique = "No plan to critique."
        return state_to_dict(current)

    system_prompt = (
        "You are an Adversarial 'Red Team' Validation Architect.\n"
        "Your goal is to BREAK the proposed test plan by finding edge cases, safety risks, and logic flaws.\n"
        "Critique aggressively. Ask yourself:\n"
        "1. Will this DESTROY data on the wrong drive? (Safety)\n"
        "2. Is the host state valid for this test? (Preconditions)\n"
        "3. What happens if the network drops mid-command? (Robustness)\n"
        "4. Is this test actually verifying the requirement, or just running a command? (Validity)\n"
        "If the plan is flawless, reply with 'APPROVED'.\n"
        "Otherwise, provide a numbered list of 'Red Team Findings' explaining why the plan is risky or incomplete."
    )
    
    user_prompt = f"Current Query: {current.query}\nProposed Plan:\n{current.plan}"

    try:
        response = chat_completion(
            cfg.ollama_base_url,
            cfg.planner_model, # Use planner model for reasoning
            system_prompt,
            user_prompt,
            cfg.request_timeout_sec,
        )
        current.critique = response
        
        # If critique is severe, potentially route back to planner?
        # For now, we just attach the critique. The Supervisor can notice "APPROVED" missing.
        
    except Exception as exc:
        current.error = f"Critic failed: {exc}"

    return state_to_dict(current)
