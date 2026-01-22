"""Policy engine for enforcing execution guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import json
import re

from src.domain.dry_run import check_command_safety, RiskLevel


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str = ""


DEFAULT_POLICY = {
    "require_approval_patterns": [
        r"\bnvme\s+fw-(download|commit|activate)\b",
        r"\bnvme\s+format\b",
        r"\bnvme\s+sanitize\b",
        r"\bblkdiscard\b",
        r"\bdd\s+if=",
        r"\bmkfs\b",
    ],
    "block_patterns": [
        r"\brm\s+-rf\s+/\b",
    ],
}


def _load_policy(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return DEFAULT_POLICY
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return DEFAULT_POLICY


def evaluate_command_policy(
    command: str,
    *,
    user_context: str = "",
    policy_path: Optional[str] = None,
) -> PolicyDecision:
    """Evaluate command against policy rules."""
    if not command:
        return PolicyDecision(allowed=False, requires_approval=False, reason="Empty command")
    context_lower = user_context.lower()
    if "force" in context_lower:
        # Explicit force can override approval requirement but not block patterns.
        pass

    path = Path(policy_path or Path(__file__).resolve().parents[2] / "configs" / "policy.json")
    policy = _load_policy(path)
    for pattern in policy.get("block_patterns", []):
        if re.search(pattern, command, re.IGNORECASE):
            return PolicyDecision(allowed=False, requires_approval=False, reason="Command blocked by policy")

    for pattern in policy.get("require_approval_patterns", []):
        if re.search(pattern, command, re.IGNORECASE):
            if "force" in context_lower:
                return PolicyDecision(allowed=True, requires_approval=False, reason="Force override provided")
            return PolicyDecision(allowed=False, requires_approval=True, reason="Command requires approval")

    # Map destructive risk levels to approval requirement.
    safety = check_command_safety(command)
    if safety.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        if "force" in context_lower:
            return PolicyDecision(allowed=True, requires_approval=False, reason="Force override provided")
        return PolicyDecision(allowed=False, requires_approval=True, reason="High-risk command requires approval")

    return PolicyDecision(allowed=True, requires_approval=False, reason="Allowed")
