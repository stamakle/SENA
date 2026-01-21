"""Validator node for checking outputs vs expectations."""

from __future__ import annotations

from src.agent.live_memory import get_live_entry
from src.graph.state import GraphState, coerce_state, state_to_dict
from pathlib import Path
import os


def _live_path() -> Path:
    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def validator_node(state: GraphState | dict) -> dict:
    """Validate last live output or context against expectations."""

    current = coerce_state(state)
    if current.session_id:
        entry = get_live_entry(_live_path(), current.session_id)
        # Use existing entry or current.last_live_output if already set
        if not entry and current.last_live_output:
             # creating a fake entry for validation
             entry = {"output": current.last_live_output}
    else:
        entry = {"output": current.last_live_output} if current.last_live_output else None

    if entry and entry.get("output"):
        output = entry["output"]
        
        # Golden State Validation Logic
        validation_msgs = []
        
        # Check 1: Critical Warnings in NVMe SMART Log
        # We try to detect if it's a SMART log JSON string
        if isinstance(output, str) and ("critical_warning" in output or "temperature" in output):
            import json
            try:
                # Naive JSON extraction (similar to ssh_client logic, but simpler here)
                start = output.find('{')
                if start != -1:
                    data = json.loads(output[start:])
                    if "critical_warning" in data:
                        cw = int(data["critical_warning"])
                        if cw != 0:
                            validation_msgs.append(f"❌ FAILING: Critical Warning is non-zero ({cw}).")
                        else:
                            validation_msgs.append("✅ PASS: Critical Warning is 0.")
                    
                    if "temperature" in data:
                        temp = int(data["temperature"])
                        # Basic threshold check
                        if temp > 70: # Celsius
                            validation_msgs.append(f"⚠️ WARNING: High Temperature detected ({temp}C).")
                        else:
                            validation_msgs.append(f"✅ PASS: Temperature is nominal ({temp}C).")
            except Exception:
                pass # Not JSON or parse error

        # Check 2: Error keywords in text output
        if isinstance(output, str):
            lower_out = output.lower()
            if "error" in lower_out or "fail" in lower_out:
                # Exclude common false positives if needed
                validation_msgs.append("⚠️ NOTICE: Output contains 'error' or 'fail'. Review manually.")
            else:
                 validation_msgs.append("✅ PASS: No explicit error keywords found in text.")

        if validation_msgs:
            current.response = "Golden State Validation:\n" + "\n".join(validation_msgs)
        else:
             current.response = (
                "Validation check:\n"
                "- Live output is available. Please specify the exact expected values if not covered by standard checks."
            )
    elif current.context:
        current.response = (
            "Validation check:\n"
            "- Context is available from RAG. Provide expected outcomes to validate."
        )
    else:
        current.response = (
            "Validation check:\n"
            "- No live output or context available. Run a live command or provide a test case ID."
        )
    return state_to_dict(current)
