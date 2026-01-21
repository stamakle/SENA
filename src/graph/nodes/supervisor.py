"""Supervisor routing node for LangGraph."""

from __future__ import annotations

import os
import re
from pathlib import Path

from src.agent.live_memory import get_live_proposed
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.retrieval.query_parser import parse_query


# Step 12: Graph supervisor (routing).


def supervisor_node(state: GraphState | dict) -> dict:
    """Route a request to the right worker based on simple intent."""

    current = coerce_state(state)
    query = current.query.strip()
    if not query:
        current.route = "help"
        return state_to_dict(current)

    approval_intent = _approval_intent(query)
    if approval_intent and current.session_id:
        proposed = get_live_proposed(_live_path(), current.session_id)
        if proposed and proposed.get("name"):
            name = str(proposed.get("name", "")).strip()
            current.augmented_query = f"/live {approval_intent} {name}".strip()
            current.route = "live_rag"
            return state_to_dict(current)

    lower = query.lower()
    if lower.startswith("/plan"):
        current.route = "planner"
        return state_to_dict(current)
    if lower.startswith("/validate"):
        current.route = "validator"
        return state_to_dict(current)
    if lower.startswith("/report"):
        current.route = "report"
        return state_to_dict(current)
    if lower.startswith("/summary") or lower.startswith("/summarize"):
        current.route = "summarize"
        return state_to_dict(current)
    if lower.startswith("/debug"):
        current.route = "debug"
        return state_to_dict(current)
    if lower.startswith("/audit"):
        current.route = "audit"
        return state_to_dict(current)
    if lower.startswith("/memory"):
        current.route = "memory"
        return state_to_dict(current)
    if lower.startswith("/safety"):
        current.route = "safety"
        return state_to_dict(current)
    if lower.startswith("/health") or lower.startswith("/check"):
        current.route = "health"
        return state_to_dict(current)
    if lower.startswith("/inventory"):
        current.route = "inventory"
        return state_to_dict(current)
    if lower.startswith("/regress") or lower.startswith("/regression"):
        current.route = "regression"
        return state_to_dict(current)
    if lower.startswith("/metrics"):
        current.route = "metrics"
        return state_to_dict(current)
    if lower.startswith("/ingest"):
        current.route = "ingest"
        return state_to_dict(current)
    if lower.startswith("/policy"):
        current.route = "policy"
        return state_to_dict(current)
    if lower.startswith("/feedback"):
        current.route = "feedback"
        return state_to_dict(current)
    if lower.startswith("/recover") or lower.startswith("/recovery"):
        current.route = "recovery"
        return state_to_dict(current)
    if lower.startswith("/test") or lower.startswith("/testcase"):
        current.route = "orchestrator"
        return state_to_dict(current)
    if "health check" in lower:
        current.route = "health"
        return state_to_dict(current)
    if "inventory" in lower and ("rack" in lower or "nvme" in lower):
        current.route = "inventory"
        return state_to_dict(current)
    if "regression" in lower:
        current.route = "regression"
        return state_to_dict(current)
    if "metrics" in lower and "summary" in lower:
        current.route = "metrics"
        return state_to_dict(current)
    if "policy" in lower and "settings" in lower:
        current.route = "policy"
        return state_to_dict(current)
    if "feedback" in lower and "log" in lower:
        current.route = "feedback"
        return state_to_dict(current)
    if "recovery" in lower or "retry steps" in lower:
        current.route = "recovery"
        return state_to_dict(current)

    if _is_orchestrator_query(query):
        current.route = "orchestrator"
        return state_to_dict(current)
    if lower.startswith("approve ") or lower.startswith("reject "):
        current.augmented_query = f"/live {query.strip()}"
        current.route = "live_rag"
        return state_to_dict(current)

    if _is_help_alias(query):
        current.route = "help"
        return state_to_dict(current)

    augmented, filters, tables, step_mode = parse_query(query, current.history)
    current.augmented_query = augmented
    current.filters = filters
    current.tables = tables
    current.step_mode = step_mode
    if _is_live_rag_query(augmented):
        current.route = "live_rag"
    else:
        current.route = "rag"
    return state_to_dict(current)


def _live_path() -> Path:
    """Return the session live storage path."""

    return Path(
        os.getenv(
            "SENA_LIVE_PATH",
            str(Path(__file__).resolve().parents[3] / "session_live.json"),
        )
    )


def _approval_intent(query: str) -> str:
    """Return approve/reject intent from a short reply."""

    lower = query.strip().lower()
    if not lower:
        return ""
    approve_phrases = {
        "yes",
        "y",
        "approve",
        "ok",
        "okay",
        "sure",
        "go ahead",
        "do it",
        "accept",
        "approve it",
        "yes approve",
    }
    reject_phrases = {
        "no",
        "n",
        "reject",
        "deny",
        "nope",
        "don't",
        "do not",
        "reject it",
        "no reject",
    }
    if lower in approve_phrases:
        return "approve"
    if lower in reject_phrases:
        return "reject"
    if lower.startswith("approve ") or lower.startswith("approve:"):
        return "approve"
    if lower.startswith("reject ") or lower.startswith("reject:"):
        return "reject"
    return ""


def _is_help_alias(query: str) -> bool:
    """Return True when query is /help or a close typo (e.g., /helpo)."""

    lower = query.strip().lower()
    if not lower.startswith("/"):
        return False
    token = lower[1:]
    if token == "help":
        return True
    if len(token) < 3 or len(token) > 6:
        return False
    # simple edit-distance check to allow small typos
    target = "help"
    return _edit_distance(token, target) <= 1


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein distance for short tokens."""

    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(
                min(
                    prev[j] + 1,
                    curr[j - 1] + 1,
                    prev[j - 1] + cost,
                )
            )
        prev = curr
    return prev[-1]


def _looks_like_rack_drive_query(query: str) -> bool:
    """Return True when the query is asking for rack drive inventory."""

    lower = query.lower()
    if "rack" not in lower:
        return False
    if "nvme" in lower or "nvem" in lower or "ssd" in lower:
        return True
    if re.search(r"\bdrive(?:s)?\b", lower):
        return True
    if re.search(r"\bdisk(?:s)?\b", lower):
        return True
    return False


def _looks_like_nvme_error_query(query: str) -> bool:
    """Return True when the query asks for NVMe error logs on a host."""

    lower = query.lower()
    if "nvme" not in lower:
        return False
    if not any(term in lower for term in ("error", "errors", "error-log", "error log", "error logs", "smart-log", "smart log")):
        return False
    if re.search(r"(?:service\s*tag|system\s*id|hostname|host|server|system)\s*[:#]?\s*[\w.-]+", query, re.IGNORECASE):
        return True
    match = re.search(r"\b(?:on|from|in|for)\s+([\w.-]+)", query, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip().lower()
        if candidate not in {"rack", "racks"}:
            return True
    if re.search(r"\b(?=[A-Za-z0-9_-]{6,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+\b", query):
        return True
    return False


def _is_live_rag_query(query: str) -> bool:
    """Return True when the query looks like a live SSH request."""

    lower = query.lower()
    followup_phrases = (
        "this output",
        "that output",
        "last output",
        "previous output",
        "this log",
        "that log",
        "last log",
        "previous log",
        "that result",
        "this result",
    )
    if any(phrase in lower for phrase in followup_phrases):
        return False
    if _looks_like_rack_drive_query(query):
        return True
    if _looks_like_nvme_error_query(query):
        return True
    host_blacklist = {
        "lscpu",
        "lspci",
        "lsblk",
        "dmesg",
        "journalctl",
        "nvme",
        "uname",
        "hostname",
        "ip",
        "cat",
        "that",
        "this",
        "last",
        "previous",
        "output",
        "log",
        "logs",
        "result",
    }
    if lower.startswith("/live"):
        return True
    if lower.startswith("/ssh"):
        return True
    if "ssh to" in lower or "ssh into" in lower:
        return True
    if any(term in lower for term in ("run", "execute", "get", "fetch", "summarize")):
        if any(term in lower for term in ("host", "hostname", "service tag", "system id", "system_id", "from", "on")):
            return True
        if re.search(r"`[^`]+`|\"[^\"]+\"|'[^']+'", query):
            return True
        host_match = re.search(r"\b(?:run|execute|get|fetch|summarize)\b\s+.+\s+\b(?:on|from)\b\s+([\w.-]+)", lower)
        if host_match and host_match.group(1) not in host_blacklist:
            return True
    if any(cmd in lower for cmd in ("lscpu", "lspci", "lsblk", "dmesg", "journalctl", "nvme list", "ip -4 addr show", "uname -a")):
        host_match = re.search(r"\b(?:on|from)\b\s+([\w.-]+)", lower)
        if host_match and host_match.group(1) not in host_blacklist:
            return True
    return False


def _is_orchestrator_query(query: str) -> bool:
    """Return True when the query should route to the orchestration node."""

    lower = query.lower()
    if "audit" in lower:
        return True
    if lower.startswith("/test") or lower.startswith("/testcase"):
        return True
    if lower.startswith("/fw") or "firmware update" in lower or "update firmware" in lower:
        return True
    if "run" in lower or "execute" in lower or "start" in lower:
        if "testcase" in lower or "test case" in lower:
            return True
        if re.search(r"\b(tc|dsstc)-\d+\b", lower):
            return True
    return False
