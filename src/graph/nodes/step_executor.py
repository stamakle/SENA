"""Step Executor Node for Iterative Plan Execution (Recommendation #1).

This node implements the Plan-Execute-Observe-Refine loop for autonomous
multi-step task execution. It pops actions from the plan, executes them
via SSH/tools, observes results, and routes back for refinement if needed.

Flow:
    planner/scientist → critic → step_executor → (loop or response)
    
Usage:
    The node is triggered when current.plan contains executable steps.
    It executes one step at a time and updates observations.
"""

from __future__ import annotations

import json
import re
from typing import Tuple, List, Optional

from src.config import load_config
from src.graph.state import GraphState, PlanStep, ToolRequest, ToolResult, coerce_state, state_to_dict
from src.tools.ssh_client import run_ssh_command
from src.domain.dry_run import check_command_safety
from src.domain.policy_engine import evaluate_command_policy
from src.domain.circuit_breaker import get_circuit_breaker


def _parse_plan_steps(plan: str) -> List[str]:
    """Parse a plan into executable steps.
    
    Handles various formats:
    - Numbered steps: "1. Run nvme list"
    - Bulleted steps: "- Run nvme list"
    - Commands with backticks: "`nvme smart-log /dev/nvme0`"
    """
    if not plan:
        return []
    
    steps: List[str] = []
    lines = plan.strip().splitlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip headers and non-actionable lines
        if line.startswith("#") or line.startswith("**"):
            continue
        
        # Extract numbered steps
        numbered = re.match(r"^\d+[\.\)]\s*(.+)$", line)
        if numbered:
            steps.append(numbered.group(1).strip())
            continue
        
        # Extract bulleted steps
        bulleted = re.match(r"^[-*]\s*(.+)$", line)
        if bulleted:
            steps.append(bulleted.group(1).strip())
            continue
        
        # Extract backtick commands
        backtick = re.search(r"`([^`]+)`", line)
        if backtick:
            steps.append(backtick.group(1).strip())
            continue
    
    return steps


def _parse_plan_json(plan: str) -> List[PlanStep]:
    """Parse JSON plan into structured steps."""
    if not plan:
        return []
    try:
        payload = json.loads(plan)
    except Exception:
        return []
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    parsed: List[PlanStep] = []
    for step in steps:
        try:
            parsed.append(PlanStep(**step))
        except Exception:
            continue
    return parsed


def _extract_command_from_step(step: str) -> Optional[str]:
    """Extract an executable command from a step description.
    
    Handles:
    - Direct commands: "nvme smart-log /dev/nvme0"
    - Prefixed: "Run: nvme list"
    - Backticks: "Execute `dmesg | grep nvme`"
    """
    if not step:
        return None
    
    # Check for backtick commands
    backtick = re.search(r"`([^`]+)`", step)
    if backtick:
        return backtick.group(1).strip()
    
    # Check for "Run:" or "Execute:" prefix
    prefixed = re.match(r"(?:run|execute|command):\s*(.+)$", step, re.IGNORECASE)
    if prefixed:
        return prefixed.group(1).strip()
    
    # Check if step starts with a known command
    known_commands = [
        "nvme", "dmesg", "lspci", "lsblk", "smartctl", "cat", "grep",
        "journalctl", "lscpu", "uname", "hostname", "df", "du", "free",
    ]
    
    for cmd in known_commands:
        if step.lower().startswith(cmd):
            return step
    
    return None


def _extract_host_from_step(step: str, context: str = "") -> Optional[str]:
    """Extract target host from step or context."""
    
    # Look for host patterns in step
    host_patterns = [
        r"on\s+host\s+(\S+)",
        r"on\s+(\S+)",
        r"host[:\s]+(\S+)",
        r"target[:\s]+(\S+)",
    ]
    
    for pattern in host_patterns:
        match = re.search(pattern, step, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    # Look in context for host
    for pattern in host_patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    
    return None


def step_executor_node(state: GraphState | dict) -> dict:
    """Execute the next step from the plan and observe results.
    
    Implements P1 Recommendation #1: Iterative Plan-Execute-Observe loop.
    
    This node:
    1. Pops the next action from current.plan
    2. Checks safety (dry-run for destructive commands)
    3. Checks circuit breaker for target host
    4. Executes via SSH/tool
    5. Updates current.observations
    6. Determines if more iterations are needed
    """
    current = coerce_state(state)
    cfg = load_config()
    
    # Parse plan into structured steps
    structured_steps = current.plan_steps or _parse_plan_json(current.plan)
    if not structured_steps:
        # Legacy fallback for non-JSON plans
        legacy_steps = _parse_plan_steps(current.plan)
        current.response = (
            "No valid structured steps found in the plan. "
            "Please provide a JSON plan with required fields."
        )
        if legacy_steps:
            current.response += "\nLegacy steps detected but not executed."
        return state_to_dict(current)

    # Validate required fields
    required_fields = {"step_id", "host_selector", "command", "preconditions", "expected_signals", "risk", "rollback"}
    for step in structured_steps:
        missing = [field for field in required_fields if not getattr(step, field, None) and getattr(step, field, None) != []]
        if missing:
            current.response = f"Plan validation failed. Missing fields in step {step.step_id}: {', '.join(missing)}"
            return state_to_dict(current)

    # Track execution state
    executed_steps: List[str] = []
    observations: List[str] = []
    errors: List[str] = []
    
    # Get context for host extraction
    context = f"{current.query} {current.context}"
    
    # Execute steps (with configurable max iterations)
    max_steps = 5  # Safety limit
    for idx, step in enumerate(structured_steps[:max_steps], 1):
        command = step.command.strip()
        if not command:
            observations.append(f"Step {idx}: Skipped (no command provided): {step.step_id}")
            continue

        host = step.host_selector.strip()
        if host.lower() in {"auto", "context", "from_context"}:
            host = _extract_host_from_step(command, context) or ""
        if not host:
            observations.append(f"Step {idx}: Skipped (no target host found): {step.step_id}")
            continue
        
        # Check circuit breaker
        breaker = get_circuit_breaker(host)
        if not breaker.can_execute():
            observations.append(f"Step {idx}: Skipped (host {host} circuit open): {step}")
            continue
        
        # Policy check
        policy_decision = evaluate_command_policy(command, user_context=current.query)
        if not policy_decision.allowed:
            observations.append(
                f"Step {idx}: Blocked by policy ({policy_decision.reason}): {command}"
            )
            errors.append(f"Policy blocked command: {command}")
            continue

        # Check for destructive commands
        safety = check_command_safety(command)
        if safety.requires_confirmation:
            observations.append(
                f"Step {idx}: Blocked (destructive command requires confirmation): {command}"
            )
            errors.append(f"Destructive command blocked: {command}")
            continue

        # Enforce verify/rollback for risky steps
        risk = step.risk.lower()
        if risk in {"high", "critical"}:
            if not step.verify_command or not step.rollback:
                observations.append(
                    f"Step {idx}: Blocked (risk={step.risk} requires verify_command and rollback): {step.step_id}"
                )
                errors.append(f"Missing verify/rollback for risky step {step.step_id}")
                continue
        
        # Execute command
        current.tool_requests.append(
            ToolRequest(name="ssh", args={"host": host, "command": command})
        )
        
        try:
            result = run_ssh_command(
                host,
                f"sudo -n {command}",
                cfg.ssh_config_path,
                timeout_sec=cfg.request_timeout_sec,
            )
            
            if not result.success:
                raise RuntimeError(result.stderr or f"Command failed with exit {result.exit_code}")
            # Record success
            breaker.record_success()
            executed_steps.append(f"Step {idx}: ✅ {command}")
            
            # Truncate large outputs for observations
            output_text = result.stdout or ""
            if len(output_text) > 2000:
                output_text = output_text[:2000] + "\n... (truncated)"
            observations.append(f"Step {idx} output:\n{output_text}")
            
            current.tool_results.append(
                ToolResult(
                    name="ssh",
                    stdout=result.stdout or "",
                    stderr=result.stderr or "",
                    exit_code=result.exit_code,
                    duration_sec=result.duration_sec,
                    host=host,
                    command=command,
                )
            )

            # Verify risky steps
            if risk in {"high", "critical"} and step.verify_command:
                verify_result = run_ssh_command(
                    host,
                    f"sudo -n {step.verify_command}",
                    cfg.ssh_config_path,
                    timeout_sec=cfg.request_timeout_sec,
                )
                verify_output = verify_result.stdout or ""
                verify_ok = verify_result.success
                if step.expected_signals:
                    verify_ok = verify_ok and all(sig.lower() in verify_output.lower() for sig in step.expected_signals)
                if not verify_ok:
                    errors.append(f"Step {idx} verification failed: {step.verify_command}")
                    # Attempt rollback
                    if step.rollback:
                        rollback_result = run_ssh_command(
                            host,
                            f"sudo -n {step.rollback}",
                            cfg.ssh_config_path,
                            timeout_sec=cfg.request_timeout_sec,
                        )
                        observations.append(
                            f"Rollback output:\n{(rollback_result.stdout or '')[:2000]}"
                        )
                        current.tool_results.append(
                            ToolResult(
                                name="ssh",
                                stdout=rollback_result.stdout or "",
                                stderr=rollback_result.stderr or "",
                                exit_code=rollback_result.exit_code,
                                duration_sec=rollback_result.duration_sec,
                                host=host,
                                command=step.rollback,
                            )
                        )
            
        except Exception as e:
            # Record failure
            breaker.record_failure(str(e))
            executed_steps.append(f"Step {idx}: ❌ {command}")
            errors.append(f"Step {idx} failed: {e}")
            
            current.tool_results.append(
                ToolResult(name="ssh", error=str(e), host=host, command=command)
            )
    
    # Update state with observations
    current.observations = "\n\n".join(observations)
    
    # Build response
    response_parts = ["## Plan Execution Results\n"]
    
    if executed_steps:
        response_parts.append("### Executed Steps")
        response_parts.extend(executed_steps)
        response_parts.append("")
    
    if errors:
        response_parts.append("### Errors")
        for error in errors:
            response_parts.append(f"- {error}")
        response_parts.append("")
    
    if observations:
        response_parts.append("### Observations")
        response_parts.append(current.observations)
    
    # Check if goal is met or more iterations needed
    remaining_steps = len(structured_steps) - min(len(structured_steps), max_steps)
    if remaining_steps > 0:
        response_parts.append(
            f"\n⚠️ {remaining_steps} more steps remain. "
            "Run `/execute continue` to proceed."
        )
    
    current.response = "\n".join(response_parts)
    
    return state_to_dict(current)
