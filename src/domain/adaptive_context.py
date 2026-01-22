"""Adaptive Context Window Management (Recommendation #6).

This module dynamically adjusts context window size based on query complexity,
response requirements, and model constraints. Optimized for CPU execution.

Usage:
    from src.domain.adaptive_context import calculate_context_budget
    
    budget = calculate_context_budget(query, has_live_output=True)
    print(budget.max_chunks)  # Adjusted chunk limit
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class ContextBudget:
    """Calculated context budget for a query."""
    max_chars: int
    max_chunks: int
    max_tokens: int
    summary_required: bool
    chunk_priority: str  # "recent", "relevance", "balanced"
    rationale: str


# Base limits (configurable via environment)
DEFAULT_MAX_CHARS = 4000
DEFAULT_MAX_CHUNKS = 8
DEFAULT_MAX_TOKENS = 2048

# Query type patterns
SIMPLE_QUERY_PATTERNS = [
    r"^what is",
    r"^show me",
    r"^list",
    r"^get",
    r"^/live",
    r"^/ssh",
]

COMPLEX_QUERY_PATTERNS = [
    r"analyze.*correlat",
    r"compare.*across",
    r"troubleshoot",
    r"root cause",
    r"why did.*fail",
    r"explain.*behavior",
    r"multi.?step",
]

LIVE_OUTPUT_KEYWORDS = [
    "dmesg", "journal", "lspci", "lscpu", "nvme list",
    "smart-log", "error-log", "lsblk",
]


def _is_simple_query(query: str) -> bool:
    """Check if query is a simple lookup/extraction."""
    query_lower = query.lower().strip()
    for pattern in SIMPLE_QUERY_PATTERNS:
        if re.search(pattern, query_lower):
            return True
    return len(query.split()) <= 6


def _is_complex_query(query: str) -> bool:
    """Check if query requires complex reasoning."""
    query_lower = query.lower().strip()
    for pattern in COMPLEX_QUERY_PATTERNS:
        if re.search(pattern, query_lower):
            return True
    return len(query.split()) >= 20


def _expects_live_output(query: str) -> bool:
    """Check if query likely expects live command output."""
    query_lower = query.lower()
    return any(kw in query_lower for kw in LIVE_OUTPUT_KEYWORDS)


def calculate_context_budget(
    query: str,
    has_live_output: bool = False,
    live_output_size: int = 0,
    has_history: bool = False,
    history_token_estimate: int = 0,
    base_max_chars: int = DEFAULT_MAX_CHARS,
    base_max_chunks: int = DEFAULT_MAX_CHUNKS,
    base_max_tokens: int = DEFAULT_MAX_TOKENS,
) -> ContextBudget:
    """Calculate adaptive context budget based on query and state.
    
    Args:
        query: User query
        has_live_output: Whether live output is available
        live_output_size: Size of live output in chars
        has_history: Whether conversation history exists
        history_token_estimate: Estimated tokens in history
        base_max_chars: Base character limit
        base_max_chunks: Base chunk limit
        base_max_tokens: Base token limit
        
    Returns:
        ContextBudget with adjusted limits
    """
    max_chars = base_max_chars
    max_chunks = base_max_chunks
    max_tokens = base_max_tokens
    summary_required = False
    chunk_priority = "relevance"
    rationale_parts = []
    
    # Adjust for query complexity
    if _is_simple_query(query):
        # Simple queries need less context
        max_chars = int(base_max_chars * 0.5)
        max_chunks = min(3, base_max_chunks)
        max_tokens = int(base_max_tokens * 0.5)
        rationale_parts.append("Simple query - reduced context")
    elif _is_complex_query(query):
        # Complex queries need more context
        max_chars = int(base_max_chars * 1.5)
        max_chunks = min(base_max_chunks + 4, 15)
        max_tokens = min(int(base_max_tokens * 1.5), 4096)
        rationale_parts.append("Complex query - expanded context")
    
    # Adjust for live output
    if has_live_output:
        if live_output_size > 5000:
            # Large live output - reduce RAG context, prioritize live
            max_chunks = min(2, max_chunks)
            summary_required = True
            chunk_priority = "recent"
            rationale_parts.append("Large live output - minimal RAG, summary mode")
        elif live_output_size > 2000:
            max_chunks = min(4, max_chunks)
            rationale_parts.append("Moderate live output - balanced")
        else:
            rationale_parts.append("Small live output - full RAG context")
    
    # Adjust for expected live output
    if _expects_live_output(query) and not has_live_output:
        # Query expects live data but none available - provide more RAG context
        max_chunks = min(max_chunks + 2, 12)
        rationale_parts.append("Live output expected - extra RAG context")
    
    # Adjust for history
    if has_history and history_token_estimate > 500:
        # Reduce context to leave room for history
        token_reduction = min(history_token_estimate, 500)
        max_tokens = max(max_tokens - token_reduction, 512)
        max_chars = int(max_chars * 0.8)
        rationale_parts.append(f"History present - reserved {token_reduction} tokens")
    
    # Ensure minimums
    max_chars = max(max_chars, 500)
    max_chunks = max(max_chunks, 1)
    max_tokens = max(max_tokens, 256)
    
    return ContextBudget(
        max_chars=max_chars,
        max_chunks=max_chunks,
        max_tokens=max_tokens,
        summary_required=summary_required,
        chunk_priority=chunk_priority,
        rationale="; ".join(rationale_parts) if rationale_parts else "Default budget",
    )


def estimate_token_count(text: str) -> int:
    """Estimate token count for text (rough approximation for CPU).
    
    Uses word-based estimation instead of tokenizer for speed.
    Average: ~1.3 tokens per word for English text.
    """
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    # Blend word and character estimates
    return int((words * 1.3 + chars / 4) / 2)


def should_summarize_context(
    context_size: int,
    query: str,
    budget: ContextBudget,
) -> bool:
    """Determine if context should be summarized before use.
    
    Args:
        context_size: Size of assembled context in chars
        query: User query
        budget: Calculated context budget
        
    Returns:
        True if summarization should be applied
    """
    if budget.summary_required:
        return True
    
    # Summarize if context significantly exceeds budget
    if context_size > budget.max_chars * 1.5:
        return True
    
    # Summarize for simple queries with large context
    if _is_simple_query(query) and context_size > budget.max_chars * 0.8:
        return True
    
    return False


def truncate_to_budget(
    text: str,
    budget: ContextBudget,
    preserve_start: bool = True,
) -> str:
    """Truncate text to fit within context budget.
    
    Args:
        text: Text to truncate
        budget: Context budget
        preserve_start: If True, keep start of text; otherwise keep end
        
    Returns:
        Truncated text
    """
    if len(text) <= budget.max_chars:
        return text
    
    if preserve_start:
        return text[:budget.max_chars - 20] + "\n... (truncated)"
    else:
        return "... (truncated)\n" + text[-(budget.max_chars - 20):]
