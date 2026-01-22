"""Retrieval node for LangGraph (RAG context builder)."""

from __future__ import annotations

from src.config import load_config
from src.db.postgres import get_connection
from src.graph.state import GraphState, coerce_state, state_to_dict
from src.llm.ollama_client import embed_text
from src.retrieval.context_builder import build_context
from src.retrieval.pipeline import extract_chunks, hybrid_search
from src.retrieval.reranker import rerank_results

# P1 #5: Query expansion for domain-specific synonyms
from src.domain.query_expansion import expand_query


# Step 12: Graph retrieval node.


def retrieval_node(state: GraphState | dict) -> dict:
    """Retrieve and build context for the current query."""

    current = coerce_state(state)
    cfg = load_config()
    query = current.augmented_query or current.query
    tables = current.tables or ["test_cases", "system_logs"]

    # P1 #5: Expand query with domain-specific synonyms
    expanded_query = expand_query(query)

    # Rec #16: Spec-RAG. Dynamically include 'specs' table if query warrants it.
    # This allows fetching normative references for behavior.
    if any(k in expanded_query.lower() for k in ["spec", "standard", "nvme", "compliance", "behavior"]):
        if "specs" not in tables:
            tables.append("specs")

    conn = None
    try:
        conn = get_connection(cfg.pg_dsn)
        # P1 #5: Use expanded query for better embedding coverage
        embedding = embed_text(
            cfg.ollama_base_url,
            cfg.embed_model,
            expanded_query,
            cfg.embed_timeout_sec,
        )
        records = hybrid_search(
            conn,
            expanded_query,  # P1 #5: Use expanded query for BM25 search
            embedding,
            current.filters,
            limit=cfg.top_k_bm25,
            tables=tables,
        )
        chunks = extract_chunks(records, step_mode=current.step_mode)
        rerank_limit = min(cfg.top_k_rerank, cfg.max_context_chunks)
        reranked = rerank_results(query, chunks, rerank_limit)  # Original query for reranking
        # P2 #6: Adaptive Context Window
        from src.domain.adaptive_context import calculate_context_budget
        
        budget = calculate_context_budget(
            query=query,
            has_live_output=bool(current.last_live_output),
            live_output_size=len(current.last_live_output or ""),
            base_max_chars=cfg.max_context_chars,
            base_max_chunks=cfg.max_context_chunks,
        )
        
        context, citations = build_context(
            reranked,
            max_chunks=budget.max_chunks,  # Use adaptive limits
            max_chars=budget.max_chars,
        )
        current.context = context
        current.citations = citations
    except Exception as exc:
        current.error = str(exc)
    finally:
        if conn is not None:
            conn.close()

    return state_to_dict(current)
