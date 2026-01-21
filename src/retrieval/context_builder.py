"""Context assembly helpers for RAG responses.

This module creates a compact context block with citations.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# Step 8: Build the answer context.


def build_context(
    chunks: List[Dict[str, Any]],
    max_chunks: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    """Build a context string and simple citations list."""

    lines: List[str] = []
    citations: List[Dict[str, str]] = []
    count = 0
    total_chars = 0
    for chunk in chunks:
        if max_chunks is not None and count >= max_chunks:
            break
        source = chunk.get("source", "")
        chunk_id = chunk.get("id", "")
        text = chunk.get("text", "")
        citation = f"[{source}:{chunk_id}]"
        line = f"{citation} {text}"
        if max_chars is not None and total_chars + len(line) > max_chars:
            break
        lines.append(line)
        citations.append({"source": source, "id": str(chunk_id)})
        count += 1
        total_chars += len(line)
    return "\n".join(lines), citations
