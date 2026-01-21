"""Scientist Node for Hypothesis-Test Loops."""

from __future__ import annotations

from src.config import load_config
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import chat_completion

def scientist_node(state: GraphState | dict) -> dict:
    """Formulate hypotheses based on observations."""
    current = coerce_state(state)
    cfg = load_config()
    
    # We analyze the 'response' or 'last_live_output' to form a hypothesis
    observation = current.response or current.last_live_output
    if not observation:
        current.response = "No observation to analyze."
        return state_to_dict(current)

    system_prompt = (
        "You are an OEM SSD Validation Scientist.\n"
        "Analyze the provided observation/logs. Formulate a scientific hypothesis about the root cause.\n"
        "Then, propose a specific 'Experiment' (command or test) to verify or falsify this hypothesis.\n"
        "Output Format:\n"
        "Hypothesis: <text>\n"
        "Experiment: <command>"
    )

    try:
        response = chat_completion(
            cfg.ollama_base_url,
            cfg.planner_model,
            system_prompt,
            f"Observation:\n{observation}",
            cfg.request_timeout_sec,
        )
        current.response = f"{current.response}\n\n[Scientist Analysis]\n{response}"
        
        # Parse 'Experiment' to make the agent proactive (Rec #4 Refinement)
        experiment_text = []
        capture = False
        for line in response.splitlines():
            if "Experiment:" in line:
                capture = True
                # Capture the part after the label
                content = line.split("Experiment:", 1)[1].strip()
                if content:
                    experiment_text.append(content)
            elif capture:
                # Stop if we hit another section key or end (heuristic)
                if any(key in line for key in ["Hypothesis:", "Observation:", "Analysis:"]):
                    capture = False
                else:
                    experiment_text.append(line.strip())
        
        proposed_experiment = " ".join(experiment_text).strip()
        if proposed_experiment:
            current.plan = proposed_experiment
            current.response += f"\n\n🚀 **Proactive Plan Update**: I have automatically staged the following experiment based on my hypothesis:\n`{proposed_experiment}`"
    except Exception as exc:
        current.error = f"Scientist failed: {exc}"

    return state_to_dict(current)
