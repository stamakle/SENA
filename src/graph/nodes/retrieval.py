"""Retrieval node for LangGraph (RAG context builder)."""

from __future__ import annotations

from src.config import load_config
from src.db.postgres import get_connection
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import embed_text
from src.retrieval.context_builder import build_context
from src.retrieval.pipeline import extract_chunks, hybrid_search
from src.retrieval.reranker import rerank_results


# Step 12: Graph retrieval node.


def retrieval_node(state: GraphState | dict) -> dict:
    """Retrieve and build context for the current query."""

    current = coerce_state(state)
    cfg = load_config()
    query = current.augmented_query or current.query
    tables = current.tables or ["test_cases", "system_logs"]

    # Rec #16: Spec-RAG. Dynamically include 'specs' table if query warrants it.
    # This allows fetching normative references for behavior.
    if any(k in query.lower() for k in ["spec", "standard", "nvme", "compliance", "behavior"]):
        if "specs" not in tables:
            tables.append("specs")

    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        embedding = embed_text(
            cfg.ollama_base_url,
            cfg.embed_model,
            query,
            cfg.embed_timeout_sec,
        )
        records = hybrid_search(
            conn,
            query,
            embedding,
            current.filters,
            limit=cfg.top_k_bm25,
            tables=tables,
        )
        chunks = extract_chunks(records, step_mode=current.step_mode)
        rerank_limit = min(cfg.top_k_rerank, cfg.max_context_chunks)
        reranked = rerank_results(query, chunks, rerank_limit)
        context, citations = build_context(
            reranked,
            max_chunks=cfg.max_context_chunks,
            max_chars=cfg.max_context_chars,
        )
        current.context = context
        current.citations = citations
    except Exception as exc:
        current.error = str(exc)
    finally:
        if conn is not None:
            conn.close()

    return state_to_dict(current)
