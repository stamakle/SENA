"""Reranking utilities for retrieved chunks.

Uses a cross-encoder reranker when available, with a safe fallback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import os


# Step 7: Add reranking.


_CROSS_ENCODER = None


def _load_cross_encoder():
    global _CROSS_ENCODER
    if _CROSS_ENCODER is not None:
        return _CROSS_ENCODER
    model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
    except Exception:
        return None
    try:
        _CROSS_ENCODER = CrossEncoder(model_name)
        return _CROSS_ENCODER
    except Exception:
        return None


def rerank_results(query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """Return the top K chunks using a cross-encoder when available."""

    if not chunks:
        return []
    encoder = _load_cross_encoder()
    if encoder is None:
        return chunks[:top_k]
    pairs: List[Tuple[str, str]] = [(query, chunk.get("text", "")) for chunk in chunks]
    try:
        scores = encoder.predict(pairs)
    except Exception:
        return chunks[:top_k]
    ranked = sorted(zip(chunks, scores), key=lambda item: item[1], reverse=True)
    return [chunk for chunk, _ in ranked[:top_k]]
