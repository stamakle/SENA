"""Planner node for high-level SSD validation tasks."""

from __future__ import annotations


import json
from typing import List
from src.config import load_config
from src.graph.state import GraphState, PlanStep, coerce_state, state_to_dict
from src.llm.ollama_client import chat_completion

def _fallback_plan(query: str) -> List[PlanStep]:
    """Return a safe, deterministic plan when LLM is unavailable."""
    steps: List[PlanStep] = []
    host_selector = "from_context"
    steps.append(
        PlanStep(
            step_id="step-1-inventory",
            host_selector=host_selector,
            command="nvme list",
            preconditions=["SSH access to target host"],
            expected_signals=["/dev/nvme"],
            risk="low",
            rollback="",
            verify_command=None,
        )
    )
    steps.append(
        PlanStep(
            step_id="step-2-smart",
            host_selector=host_selector,
            command="nvme smart-log /dev/nvme0",
            preconditions=["Replace /dev/nvme0 with the target device from step-1"],
            expected_signals=["critical_warning", "temperature"],
            risk="low",
            rollback="",
            verify_command=None,
        )
    )
    steps.append(
        PlanStep(
            step_id="step-3-error-log",
            host_selector=host_selector,
            command="nvme error-log /dev/nvme0",
            preconditions=["Replace /dev/nvme0 with the target device from step-1"],
            expected_signals=["status"],
            risk="low",
            rollback="",
            verify_command=None,
        )
    )
    steps.append(
        PlanStep(
            step_id="step-4-kernel-logs",
            host_selector=host_selector,
            command="dmesg -T --level=err,crit,alert,emerg | tail -n 200",
            preconditions=["Kernel logs available"],
            expected_signals=["error", "nvme"],
            risk="low",
            rollback="",
            verify_command=None,
        )
    )
    steps.append(
        PlanStep(
            step_id="step-5-pcie",
            host_selector=host_selector,
            command="lspci -vv | grep -i -A20 nvme",
            preconditions=["PCIe tools available"],
            expected_signals=["LnkSta", "LnkCap"],
            risk="low",
            rollback="",
            verify_command=None,
        )
    )
    return steps


def planner_node(state: GraphState | dict) -> dict:
    """Generate a high-level plan for the requested task using LLM."""
    current = coerce_state(state)
    query = current.augmented_query or current.query
    cfg = load_config()

    system_prompt = (
        "You are an Expert SSD Validation Planner.\n"
        "Return ONLY valid JSON with a top-level key 'steps' containing an array of objects.\n"
        "Each step must include:\n"
        "- step_id (string)\n"
        "- host_selector (string)\n"
        "- command (string)\n"
        "- preconditions (array of strings)\n"
        "- expected_signals (array of strings)\n"
        "- risk (low|medium|high|critical)\n"
        "- rollback (string)\n"
        "- verify_command (string, optional)\n"
        "Focus on NVMe tools (nvme-cli), Linux commands, and validation best practices.\n"
        "Do not include prose outside JSON."
    )

    try:
        response = chat_completion(
            cfg.ollama_base_url,
            cfg.planner_model,
            system_prompt,
            f"User Request: {query}",
            cfg.request_timeout_sec,
        )
        plan_steps: list[PlanStep] = []
        try:
            parsed = json.loads(response)
            steps = parsed.get("steps", []) if isinstance(parsed, dict) else []
            for step in steps:
                plan_steps.append(PlanStep(**step))
        except Exception as exc:
            current.error = f"Planner returned invalid JSON: {exc}"
            plan_steps = _fallback_plan(query)
        current.plan_steps = plan_steps
        steps_payload = []
        for step in plan_steps:
            if hasattr(step, "model_dump"):
                steps_payload.append(step.model_dump())
            else:
                steps_payload.append(step.dict())
        current.plan = json.dumps({"steps": steps_payload}, indent=2)
        if current.error:
            current.response = f"**Fallback Plan (LLM unavailable):**\n{current.plan}"
        else:
            current.response = f"**Proposed Plan (JSON):**\n{current.plan}"
    except Exception as exc:
        current.error = f"Planner failed: {exc}"
        plan_steps = _fallback_plan(query)
        current.plan_steps = plan_steps
        steps_payload = []
        for step in plan_steps:
            if hasattr(step, "model_dump"):
                steps_payload.append(step.model_dump())
            else:
                steps_payload.append(step.dict())
        current.plan = json.dumps({"steps": steps_payload}, indent=2)
        current.response = f"**Fallback Plan (LLM unavailable):**\n{current.plan}"

    return state_to_dict(current)
