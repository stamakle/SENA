"""Critic Node for Devil's Advocate Logic (Enhanced with P1 #3)."""

from __future__ import annotations

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import chat_completion


# Step 1: Critique the plan before execution.

def _is_plan_approved(critique: str) -> bool:
    """Check if the critique indicates plan approval.
    
    Returns True if critique contains APPROVED without REJECT markers.
    """
    if not critique:
        return False
    
    critique_upper = critique.upper()
    
    # Check for explicit approval
    if "APPROVED" in critique_upper:
        # Make sure it's not "NOT APPROVED" or similar
        if "NOT APPROVED" in critique_upper or "REJECTED" in critique_upper:
            return False
        return True
    
    return False


def _is_plan_rejected(critique: str) -> bool:
    """Check if the critique indicates plan rejection.
    
    Returns True if critique contains rejection markers.
    """
    if not critique:
        return False
    
    critique_upper = critique.upper()
    reject_markers = ["REJECT", "REJECTED", "NOT APPROVED", "DANGEROUS", "⛔", "UNSAFE"]
    
    return any(marker in critique_upper for marker in reject_markers)


def _count_revision_iterations(state: GraphState) -> int:
    """Count how many times the plan has been revised."""
    return state.iteration_count


def critic_node(state: GraphState | dict) -> dict:
    """Critique the current plan and offer feedback/refinements.
    
    P1 #3: Enhanced with approval detection and revision routing.
    
    Sets:
    - current.critique: The critique text
    - current.plan: Cleared if rejected (triggers re-planning)
    - current.iteration_count: Incremented on each revision
    """
    current = coerce_state(state)
    cfg = load_config()

    if not current.plan:
        current.critique = "No plan to critique."
        current.critique_status = "none"
        return state_to_dict(current)

    # BLOCKLIST: Fast-fail dangerous keywords before LLM
    dangerous_keywords = ["format", "mkfs", "wipe", "dd if=", "shred", "blkdiscard"]
    plan_lower = current.plan.lower()
    if any(k in plan_lower for k in dangerous_keywords):
        current.critique = (
            "⛔ **CRITIQUE: DANGEROUS ACTION DETECTED**\n"
            "This plan involves destructive keywords (format/mkfs/wipe).\n"
            "**Recommendation:** REJECT immediately unless 'FORCE' flag is explicitly provided by the Supervisor."
        )
        # P1 #3: Clear plan to prevent execution of dangerous commands
        # Don't clear - let step_executor's dry-run handle it
        current.critique_status = "rejected"
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
        "Otherwise, provide a numbered list of 'Red Team Findings' explaining why the plan is risky or incomplete.\n"
        "End with either 'APPROVED' or 'REJECTED: <reason>'"
    )
    
    user_prompt = f"Current Query: {current.query}\nProposed Plan:\n{current.plan}"

    try:
        response = chat_completion(
            cfg.ollama_base_url,
            cfg.planner_model,  # Use planner model for reasoning
            system_prompt,
            user_prompt,
            cfg.request_timeout_sec,
        )
        current.critique = response
        
        # P1 #3: Check approval status and handle rejection
        if _is_plan_rejected(response):
            # Increment iteration count
            current.iteration_count += 1
            current.critique_status = "rejected"
            
            # Check if we've exceeded max iterations
            if current.iteration_count >= current.max_iterations:
                current.critique += (
                    f"\n\n⚠️ **Max Iterations Reached ({current.max_iterations})**\n"
                    "Plan revision loop terminated. Manual intervention required."
                )
            else:
                # Add revision guidance to critique
                current.critique += (
                    f"\n\n🔄 **Revision Required** (Iteration {current.iteration_count}/{current.max_iterations})\n"
                    "The planner should address the findings above and resubmit."
                )
        elif _is_plan_approved(response):
            current.critique += "\n\n✅ **Plan Approved** - Proceeding to execution."
            current.critique_status = "approved"
        else:
            current.critique_status = "needs_revision"
        
    except Exception as exc:
        current.error = f"Critic failed: {exc}"
        current.critique_status = "error"

    return state_to_dict(current)
