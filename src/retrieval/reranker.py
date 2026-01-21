"""Reranking utilities for retrieved chunks.

This module provides a placeholder reranker that can be swapped for a local
cross-encoder or LLM-based reranker.
"""

from __future__ import annotations

from typing import Any, Dict, List


# Step 7: Add reranking.


def rerank_results(query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """Return the top K chunks in their current order.

    Replace this logic with a local reranker model when ready.
    """

    _ = query
    return chunks[:top_k]
