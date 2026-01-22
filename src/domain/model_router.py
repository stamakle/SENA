"""Model Selection Router for Latency-Critical Paths (Recommendation #20).

This module routes queries to appropriate model sizes based on complexity,
providing faster responses for simple queries while maintaining quality
for complex reasoning tasks.

Usage:
    from src.domain.model_router import route_to_model, QueryComplexity
    
    model = route_to_model("What is the BDF?", cfg)
    # Returns cfg.chat_fast_model for simple queries
    
    model = route_to_model("Analyze the SMART trends and correlate with PCIe errors", cfg)
    # Returns cfg.chat_model for complex queries
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Set


class QueryComplexity(Enum):
    """Query complexity levels for model routing."""
    SIMPLE = "simple"       # Single fact extraction, yes/no, definitions
    MODERATE = "moderate"   # Basic analysis, list generation, formatting
    COMPLEX = "complex"     # Multi-step reasoning, correlation, planning


@dataclass
class RoutingDecision:
    """Result of model routing decision."""
    model: str
    complexity: QueryComplexity
    reason: str
    estimated_tokens: int


# Patterns indicating simple queries (fast model)
SIMPLE_PATTERNS: List[str] = [
    r"^what is (?:the |a )?(?:bdf|ip|hostname|service tag|serial)",
    r"^show (?:me )?(?:the )?(?:ip|hostname|hosts?|systems?|drives?)",
    r"^list (?:the )?(?:hosts?|drives?|systems?|namespaces?)",
    r"^get (?:the )?(?:hostname|ip|temperature|firmware)",
    r"^is (?:the |this )?",
    r"^how many",
    r"^which (?:drive|host|system)",
    r"^where is",
    r"^when did",
    r"^/live \w+",  # Live commands are simple dispatches
    r"^/ssh ",
    r"^help$",
    r"^\?$",
]

# Patterns indicating complex queries (full model)
COMPLEX_PATTERNS: List[str] = [
    r"analyze|analysis",
    r"correlate|correlation",
    r"compare|comparison",
    r"explain why|explain how",
    r"what (?:caused|is causing)",
    r"troubleshoot|debug",
    r"investigate",
    r"root cause",
    r"trend|pattern",
    r"predict|forecast",
    r"plan|strategy|approach",
    r"optimize|improve",
    r"multiple.*(?:and|then|after)",
    r"step.by.step|multi.step",
    r"if.*then|when.*should",
    r"recommend|suggest|advise",
]

# Keywords that add complexity
COMPLEXITY_KEYWORDS: Set[str] = {
    "because", "therefore", "however", "although", "whereas",
    "analyze", "correlate", "compare", "investigate", "troubleshoot",
    "multiple", "several", "all", "every", "each",
    "relationship", "connection", "impact", "effect",
    "over time", "trend", "history", "pattern",
}

# Word count thresholds
SIMPLE_MAX_WORDS = 8
COMPLEX_MIN_WORDS = 25


def _count_complexity_keywords(query: str) -> int:
    """Count complexity-indicating keywords in query."""
    query_lower = query.lower()
    return sum(1 for kw in COMPLEXITY_KEYWORDS if kw in query_lower)


def _matches_patterns(query: str, patterns: List[str]) -> bool:
    """Check if query matches any of the patterns."""
    query_lower = query.lower().strip()
    for pattern in patterns:
        if re.search(pattern, query_lower, re.IGNORECASE):
            return True
    return False


def classify_query_complexity(query: str) -> QueryComplexity:
    """Classify query complexity for model routing.
    
    Args:
        query: User query string
        
    Returns:
        QueryComplexity level
    """
    if not query:
        return QueryComplexity.SIMPLE
    
    query = query.strip()
    words = query.split()
    word_count = len(words)
    
    # Check for simple patterns first (fast path)
    if _matches_patterns(query, SIMPLE_PATTERNS):
        return QueryComplexity.SIMPLE
    
    # Check for complex patterns
    if _matches_patterns(query, COMPLEX_PATTERNS):
        return QueryComplexity.COMPLEX
    
    # Word count heuristics
    if word_count <= SIMPLE_MAX_WORDS:
        # Short queries are usually simple
        complexity_keywords = _count_complexity_keywords(query)
        if complexity_keywords == 0:
            return QueryComplexity.SIMPLE
        return QueryComplexity.MODERATE
    
    if word_count >= COMPLEX_MIN_WORDS:
        # Long queries are usually complex
        return QueryComplexity.COMPLEX
    
    # Medium length - check for complexity indicators
    complexity_keywords = _count_complexity_keywords(query)
    if complexity_keywords >= 2:
        return QueryComplexity.COMPLEX
    elif complexity_keywords >= 1:
        return QueryComplexity.MODERATE
    
    return QueryComplexity.MODERATE


def estimate_response_tokens(query: str, complexity: QueryComplexity) -> int:
    """Estimate expected response token count.
    
    Used for setting num_predict and timeout budgets.
    """
    base_tokens = {
        QueryComplexity.SIMPLE: 100,
        QueryComplexity.MODERATE: 300,
        QueryComplexity.COMPLEX: 800,
    }
    
    # Adjust based on query characteristics
    tokens = base_tokens[complexity]
    
    query_lower = query.lower()
    if "list" in query_lower or "show all" in query_lower:
        tokens += 200
    if "explain" in query_lower:
        tokens += 150
    if "plan" in query_lower or "step" in query_lower:
        tokens += 200
    
    return min(tokens, 2048)  # Cap at 2K tokens


def route_to_model(query: str, cfg) -> RoutingDecision:
    """Route query to appropriate model based on complexity.
    
    Args:
        query: User query
        cfg: Config object with model settings
        
    Returns:
        RoutingDecision with selected model and reasoning
    """
    complexity = classify_query_complexity(query)
    estimated_tokens = estimate_response_tokens(query, complexity)
    
    if complexity == QueryComplexity.SIMPLE:
        return RoutingDecision(
            model=getattr(cfg, "chat_cpu_model", cfg.chat_fast_model),
            complexity=complexity,
            reason="Simple extraction/lookup query",
            estimated_tokens=estimated_tokens,
        )
    
    if complexity == QueryComplexity.COMPLEX:
        return RoutingDecision(
            model=getattr(cfg, "chat_gpu_model", cfg.chat_model),
            complexity=complexity,
            reason="Complex reasoning/analysis required",
            estimated_tokens=estimated_tokens,
        )
    
    # Moderate complexity - use small model as a balance
    return RoutingDecision(
        model=cfg.chat_small_model,
        complexity=complexity,
        reason="Moderate complexity query",
        estimated_tokens=estimated_tokens,
    )


def select_model_for_task(task_type: str, cfg) -> str:
    """Select model for a specific task type.
    
    Args:
        task_type: Type of task (embedding, planning, summarization, etc.)
        cfg: Config object
        
    Returns:
        Model name string
    """
    task_models = {
        "embedding": cfg.embed_model,
        "planning": cfg.planner_model,
        "summarization": cfg.summary_model,
        "chat": cfg.chat_model,
        "fast_chat": cfg.chat_fast_model,
        "small_chat": cfg.chat_small_model,
        "live_summary": cfg.live_summary_model,
    }
    
    return task_models.get(task_type, cfg.chat_model)


# Convenience function matching existing usage pattern
def select_chat_model_smart(
    query: str,
    has_context: bool,
    cfg,
) -> str:
    """Smart model selection based on query complexity.
    
    Drop-in replacement for select_chat_model with complexity routing.
    """
    decision = route_to_model(query, cfg)
    
    # If we have rich context, might need more capable model
    if has_context and decision.complexity == QueryComplexity.SIMPLE:
        # Bump to moderate for context-rich simple queries
        return cfg.chat_small_model
    
    return decision.model
