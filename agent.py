"""Local RAG agent compatible with the NiceGUI UI.

This module exposes the RAGSshAgent class expected by ui_nicegui/sena.py.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from src.agent.summary_rag import summarize_context
from src.agent.summary_session import summarize_history
from src.agent.session_memory import get_summary, set_summary
from src.cache.ttl_cache import TTLCache
from src.config import load_config
from src.db.postgres import get_connection
from src.llm.ollama_client import chat_completion, chat_completion_stream, embed_text
from src.retrieval.context_builder import build_context
from src.retrieval.pipeline import extract_chunks, hybrid_search
from src.retrieval.query_parser import parse_query
from src.retrieval.reranker import rerank_results


# Step 9: Connect the UI to the agent pipeline.


def _chunk_text(text: str, size: int = 200) -> Iterable[str]:
    """Yield fixed-size chunks to simulate streaming output."""

    for i in range(0, len(text), size):
        yield text[i : i + size]


def _debug_enabled() -> bool:
    """Return True when debug logging is enabled."""

    return os.getenv("RAG_DEBUG", "").lower() in {"1", "true", "yes"}


def _debug_log(message: str) -> None:
    """Print a debug message when RAG_DEBUG is enabled."""

    if _debug_enabled():
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[RAG DEBUG] {timestamp} {message}", flush=True)


def _help_text() -> str:
    """Return example prompts for the UI help command."""

    return "\n".join(
        [
            "Here are some free-form prompts you can try:",
            "- Show hosts in rack B1",
            "- Show hosts in rack B19",
            "- List hosts in rack B9",
            "- List systems in rack B19",
            "- Show system in rack B1",
            "- Show system with service tag SERVICE_TAG_192_168_100_130",
            "- Show hostname d5s42-len-rhe94",
            "- Show model R740 systems",
            "- List test case TC-1198",
            "- List SPDM test cases",
            "- List PCIe SSD hotplug test steps",
            "- What is the expected result for SPDM - Response While in the Link Disabled State?",
            "- List steps only for TC-15174",
            "- Show detailed steps for TC-15174",
            "- Show systems with AMD EPYC 9334",
        ]
    )


def _is_inventory_query(query: str) -> bool:
    """Return True when the query asks for a list of systems or hosts."""

    lower = query.lower()
    terms = (
        "show host",
        "show hosts",
        "list host",
        "list hosts",
        "show system",
        "show systems",
        "list system",
        "list systems",
        "inventory",
        "systems in rack",
        "system in rack",
    )
    return any(term in lower for term in terms)


def _is_test_case_query(query: str) -> bool:
    """Return True when the query targets test cases or steps."""

    lower = query.lower()
    terms = ("test case", "tc-", "test steps", "test step", "expected result")
    return any(term in lower for term in terms)


def _is_explanatory_query(query: str) -> bool:
    """Return True when the user asks for explanations or walkthroughs."""

    lower = query.lower()
    terms = (
        "explain",
        "walk me through",
        "meaning",
        "what is",
        "define",
        "clarify",
    )
    return any(term in lower for term in terms)


class RAGSshAgent:
    """RAG agent that retrieves context and generates answers locally."""

    def __init__(self) -> None:
        """Initialize configuration and caches."""

        self.config = load_config()
        self.cache = TTLCache(self.config.cache_ttl_sec)
        self._last_plan = ""
        self._summary_path = Path(
            os.getenv(
                "SENA_SUMMARY_PATH",
                str(Path(__file__).resolve().parent / "session_summaries.json"),
            )
        )

    def describe_plan(self) -> str:
        """Return a short plan string for UI display."""

        return self._last_plan

    # Step 3: Session summary helpers.

    def get_session_summary(self, session_id: str | None) -> str:
        """Return stored summary for a session."""

        if not session_id:
            return ""
        entry = get_summary(self._summary_path, session_id)
        if not entry:
            return ""
        return str(entry.get("summary", "")).strip()

    def update_session_summary(self, session_id: str | None, history: List[Dict[str, str]]) -> str:
        """Update summary for a session based on recent history."""

        if not session_id:
            return ""
        if len(history) < self.config.summary_min_messages:
            return ""

        entry = get_summary(self._summary_path, session_id)
        prev_count = int(entry.get("message_count", 0)) if entry else 0
        if len(history) - prev_count < self.config.summary_update_every:
            return str(entry.get("summary", "")).strip() if entry else ""

        summary = summarize_history(
            history,
            self.config.ollama_base_url,
            self.config.summary_model,
            self.config.request_timeout_sec,
            self.config.summary_max_tokens,
        )
        if summary:
            set_summary(self._summary_path, session_id, summary, len(history))
        return summary

    # Step 6: Provide structured inventory answers for system queries.

    def _structured_system_answer(
        self, query: str, filters: Dict[str, str], tables: List[str]
    ) -> str | None:
        """Return a direct inventory answer when filters are explicit."""

        if tables != ["system_logs"]:
            return None
        if _is_explanatory_query(query):
            return None

        allowed_filters = {
            k: v
            for k, v in filters.items()
            if k in {"rack", "hostname", "model", "system_id"} and v
        }
        if not allowed_filters and not _is_inventory_query(query):
            return None

        def _metadata_value(metadata: Dict[str, Any], keys: List[str]) -> str:
            lowered = {str(k).lower(): v for k, v in metadata.items()}
            for key in keys:
                value = lowered.get(key)
                if value:
                    return str(value)
            return ""

        clauses = []
        params: List[str] = []
        for key, value in allowed_filters.items():
            clauses.append(f"{key} = %s")
            params.append(value)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        conn = None
        try:
            conn = get_connection(self.config.pg_dsn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT system_id, hostname, model, rack, metadata
                    FROM system_logs
                    {where_sql}
                    ORDER BY hostname NULLS LAST
                    LIMIT 50
                    """,
                    params,
                )
                rows = cur.fetchall()

            if not rows:
                return "No hosts found for the specified filters."

            lines = [
                "| Hostname | Model | Rack | Service Tag | Host IP | iDRAC IP |",
                "|---|---|---|---|---|---|",
            ]
            for system_id, hostname, model, rack, metadata in rows:
                metadata = metadata or {}
                host_ip = _metadata_value(metadata, ["host ip", "host  ip"])
                idrac_ip = _metadata_value(metadata, ["idrac ip", "bmc ip"])
                lines.append(
                    f"| {hostname or 'unknown'} | {model or 'unknown'} | {rack or 'unknown'} | {system_id or '-'} | {host_ip or '-'} | {idrac_ip or '-'} |"
                )
            return "\n".join(lines)
        finally:
            if conn is not None:
                conn.close()

    # Step 6: Provide structured test case answers for TC-#### queries.

    def _structured_test_case_answer(
        self, query: str, filters: Dict[str, str], step_mode: str
    ) -> str | None:
        """Return a direct test case response when a case ID is provided."""

        case_id = filters.get("case_id")
        if not case_id:
            return None
        if _is_explanatory_query(query):
            return None

        conn = None
        try:
            conn = get_connection(self.config.pg_dsn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT case_id, name, status, type, description, precondition, steps
                    FROM test_cases
                    WHERE case_id = %s
                    LIMIT 1
                    """,
                    (case_id,),
                )
                row = cur.fetchone()

            if not row:
                return f"No test case found for {case_id}."

            case_id, name, status, case_type, description, precondition, steps = row

            def _clean_step_text(text: str) -> str:
                text = text.strip()
                if not text:
                    return text
                if "Description" in text:
                    parts = text.split("Description", 1)
                    if len(parts) == 2 and parts[1].strip():
                        return parts[1].strip()
                # Remove "Input Data (Expected: Implicit)" and simple "Input Data"
                text = re.sub(r"Input Data\s*(?:\(Expected:\s*Implicit\))?", "", text, flags=re.I)
                # Remove leading punctuation/numbers that might remain
                text = re.sub(r"^\s*[-:]?\s*\d*\s*", "", text)
                text = re.sub(r"\s+", " ", text).strip()
                return text.strip() or text

            def _format_steps(step_items: list) -> list[str]:
                numbered: list[str] = []
                seen: set[str] = set()
                for idx, step in enumerate(step_items, start=1):
                    if not isinstance(step, dict):
                        continue
                    desc = _clean_step_text(step.get("description") or "")
                    expected = _clean_step_text(step.get("expected") or "")
                    if step_mode == "detailed" and expected:
                        text = f"{desc} Expected: {expected}"
                    else:
                        text = desc
                    if text:
                        normalized = re.sub(r"\s+", " ", text).strip().lower()
                        if normalized in seen:
                            continue
                        seen.add(normalized)
                        numbered.append(f"{idx} Description {text}")
                return numbered

            if step_mode in {"steps_only", "detailed"}:
                if isinstance(steps, list):
                    formatted = _format_steps(steps)
                    if formatted:
                        lines = [
                            f"Test Case: {case_id} Name: {name or 'unknown'}",
                            f"Test Type: {case_type or 'unknown'}",
                            *formatted,
                        ]
                        return "\n".join(lines)
                return "No steps available."

            lines = [
                f"Test Case: {case_id} Name: {name or 'unknown'}",
                f"Test Type: {case_type or 'unknown'}",
            ]
            if description:
                lines.append(f"Description: {description}")
            if precondition:
                lines.append(f"Precondition: {precondition}")
            return "\n".join(lines)
        finally:
            if conn is not None:
                conn.close()

    def _walkthrough_test_case_answer(
        self, query: str, filters: Dict[str, str], step_mode: str
    ) -> str | None:
        """Return a numbered walkthrough list with explanations."""

        case_id = filters.get("case_id")
        if not case_id:
            return None
        if not _is_explanatory_query(query):
            return None

        conn = None
        try:
            conn = get_connection(self.config.pg_dsn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT case_id, name, type, steps
                    FROM test_cases
                    WHERE case_id = %s
                    LIMIT 1
                    """,
                    (case_id,),
                )
                row = cur.fetchone()

            if not row:
                return f"No test case found for {case_id}."

            case_id, name, case_type, steps = row

            def _clean_step_text(text: str) -> str:
                text = text.strip()
                if not text:
                    return text
                if "Description" in text:
                    parts = text.split("Description", 1)
                    if len(parts) == 2 and parts[1].strip():
                        return parts[1].strip()
                text = re.sub(r"^Input Data(?: Implicit)?\s*-?\s*\d*\s*", "", text, flags=re.I)
                text = re.sub(r"\bInput Data(?: Implicit)?\b", "", text, flags=re.I)
                text = re.sub(r"\s+", " ", text).strip()
                return text.strip() or text

            step_lines: List[str] = []
            if isinstance(steps, list):
                for idx, step in enumerate(steps, start=1):
                    if not isinstance(step, dict):
                        continue
                    desc = _clean_step_text(step.get("description") or "")
                    if desc:
                        step_lines.append(f"{idx} Description {desc}")

            if not step_lines:
                return "No steps available."

            template = "\n".join(
                [
                    f"Test Case: {case_id} Name: {name or 'unknown'}",
                    f"Test Type: {case_type or 'unknown'}",
                    "",
                    "Provide a numbered walkthrough list.",
                    "Use the exact step lines below and add a short explanation after each.",
                    "Format: \"<step line> - Explanation: <text>\"",
                    "",
                    *step_lines,
                ]
            )

            model = self._select_chat_model(query, ["test_cases"], filters)
            response = chat_completion(
                self.config.ollama_base_url,
                model,
                "You are a helpful assistant. Follow the formatting instructions exactly.",
                template,
                self.config.request_timeout_sec,
                num_predict=self.config.chat_max_tokens,
            )

            if re.search(r"^1\\s+Description", response, flags=re.M):
                return response.strip()

            def _explain_step(desc: str) -> str:
                lower = desc.lower()
                if "clear the sel" in lower:
                    return "Clears old errors so new issues during the test are visible."
                if "stress" in lower:
                    return "Applies sustained load to validate SSD stability under heavy I/O."
                if "review logs" in lower or "logs" in lower:
                    return "Checks for errors not captured by the SEL."
                if "check the sel" in lower:
                    return "Verifies any correctable errors were logged."
                if "diskio" in lower or "iogen" in lower or "mltt" in lower:
                    return "Uses workload tools to generate I/O and validate SSD behavior."
                return "Performs this action and captures evidence needed for validation."

            fallback_lines = [
                f"Test Case: {case_id} Name: {name or 'unknown'}",
                f"Test Type: {case_type or 'unknown'}",
            ]
            for line in step_lines:
                desc = line.split("Description", 1)[-1].strip()
                fallback_lines.append(f"{line} - Explanation: {_explain_step(desc)}")
            return "\n".join(fallback_lines)
        finally:
            if conn is not None:
                conn.close()

    def _select_chat_model(
        self, query: str, tables: List[str], filters: Dict[str, str]
    ) -> str:
        """Choose a smaller model for simple test-case lookups."""

        if tables == ["test_cases"] and (_is_test_case_query(query) or filters.get("case_id")):
            return self.config.chat_small_model
        return self.config.chat_model

    def _build_context(
        self, query: str, filters: Dict[str, str], tables: List[str], step_mode: str
    ) -> Tuple[str, List[Dict[str, str]]]:
        """Retrieve, rerank, and format context for the given query."""

        start_time = time.monotonic()
        cache_key = f"ctx:{query}:{sorted(filters.items())}:{','.join(tables)}"
        cached = self.cache.get(cache_key)
        if cached:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            _debug_log("cache hit for context")
            _debug_log(f"context_chars={len(cached[0])}")
            _debug_log(f"context_total_ms={elapsed_ms:.1f}")
            return cached

        self._last_plan = "retrieve -> rerank -> build context"
        conn = None
        try:
            conn = get_connection(self.config.pg_dsn)
            _debug_log(f"query='{query}' filters={filters} tables={tables}")
            embed_start = time.monotonic()
            embedding = embed_text(
                self.config.ollama_base_url,
                self.config.embed_model,
                query,
                self.config.request_timeout_sec,
            )
            embed_ms = (time.monotonic() - embed_start) * 1000
            _debug_log(f"embedding_dim={len(embedding)} model={self.config.embed_model}")
            _debug_log(f"embedding_ms={embed_ms:.1f}")
            retrieval_start = time.monotonic()
            records = hybrid_search(
                conn,
                query,
                embedding,
                filters,
                limit=self.config.top_k_bm25,
                tables=tables,
            )
            retrieval_ms = (time.monotonic() - retrieval_start) * 1000
            _debug_log(f"retrieved_records={len(records)}")
            _debug_log(f"retrieval_ms={retrieval_ms:.1f}")
            chunks = extract_chunks(records, step_mode=step_mode)
            rerank_start = time.monotonic()
            rerank_limit = min(self.config.top_k_rerank, self.config.max_context_chunks)
            reranked = rerank_results(query, chunks, rerank_limit)
            rerank_ms = (time.monotonic() - rerank_start) * 1000
            _debug_log(f"reranked_chunks={len(reranked)}")
            _debug_log(f"rerank_ms={rerank_ms:.1f}")
            context, citations = build_context(
                reranked,
                max_chunks=self.config.max_context_chunks,
                max_chars=self.config.max_context_chars,
            )
            if (
                self.config.summary_enabled
                and len(context) > self.config.summary_trigger_chars
            ):
                _debug_log(
                    f"summarize_context start chars={len(context)} model={self.config.summary_model}"
                )
                summary = summarize_context(
                    context,
                    self.config.ollama_base_url,
                    self.config.summary_model,
                    self.config.request_timeout_sec,
                    self.config.summary_max_tokens,
                    self.config.summary_mode,
                )
                if summary:
                    context = f"Summary:\\n{summary}"
                    _debug_log(f"summarize_context done chars={len(context)}")
            self.cache.set(cache_key, (context, citations))
            elapsed_ms = (time.monotonic() - start_time) * 1000
            _debug_log(f"context_chars={len(context)}")
            _debug_log(f"context_total_ms={elapsed_ms:.1f}")
            return context, citations
        except Exception as exc:
            _debug_log(f"error={exc}")
            return "", []
        finally:
            if conn is not None:
                conn.close()

    def prepare_streaming_prompt(
        self,
        question: str,
        system_prompt: str,
        history: List[Dict[str, str]] | None = None,
        session_id: str | None = None,
    ) -> Tuple[Dict[str, Any], Iterable[str]]:
        """Prepare context and return a generator for streaming output."""

        start_time = time.monotonic()
        history = history or []
        if question.strip().lower() == "/help":
            return {"context": ""}, _chunk_text(_help_text())
        augmented_query, filters, tables, step_mode = parse_query(question, history)
        structured = self._structured_system_answer(augmented_query, filters, tables)
        if structured:
            _debug_log("structured_answer=system_logs")
            _debug_log(f"rag_total_ms={(time.monotonic() - start_time) * 1000:.1f}")
            return {"context": ""}, _chunk_text(structured)
        walkthrough = self._walkthrough_test_case_answer(augmented_query, filters, step_mode)
        if walkthrough:
            _debug_log("structured_answer=test_case_walkthrough")
            _debug_log(f"rag_total_ms={(time.monotonic() - start_time) * 1000:.1f}")
            return {"context": ""}, _chunk_text(walkthrough)
        structured_test = self._structured_test_case_answer(augmented_query, filters, step_mode)
        if structured_test:
            _debug_log("structured_answer=test_cases")
            _debug_log(f"rag_total_ms={(time.monotonic() - start_time) * 1000:.1f}")
            return {"context": ""}, _chunk_text(structured_test)
        context, _citations = self._build_context(augmented_query, filters, tables, step_mode)
        session_summary = self.get_session_summary(session_id)

        if context:
            if session_summary:
                user_prompt = (
                    f"Session Summary:\n{session_summary}\n\n"
                    f"Context:\n{context}\n\nQuestion: {augmented_query}"
                )
            else:
                user_prompt = f"Context:\n{context}\n\nQuestion: {augmented_query}"
        else:
            if session_summary:
                user_prompt = f"Session Summary:\n{session_summary}\n\nQuestion: {augmented_query}"
            else:
                user_prompt = augmented_query

        if _is_explanatory_query(augmented_query):
            user_prompt = (
                f"{user_prompt}\n\n"
                "Instruction: Format the response as a strictly numbered list (1., 2., 3...).\n"
                "Each item must start on a new line.\n"
                "Do NOT use a single block paragraph.\n"
                "Example format:\n"
                "1. **Step Name**: Explanation...\n"
                "2. **Step Name**: Explanation..."
            )

        model = self._select_chat_model(augmented_query, tables, filters)
        _debug_log(f"generation_started model={model} prompt_chars={len(user_prompt)}")
        _debug_log("waiting_on_ollama")
        gen_start = time.monotonic()
        stream = chat_completion_stream(
            self.config.ollama_base_url,
            model,
            system_prompt,
            user_prompt,
            self.config.request_timeout_sec,
            num_predict=self.config.chat_max_tokens,
        )

        def _timed_stream():
            first_token = True
            for chunk in stream:
                if first_token:
                    first_token = False
                    _debug_log(
                        f"first_token_ms={(time.monotonic() - gen_start) * 1000:.1f}"
                    )
                yield chunk
            gen_ms = (time.monotonic() - gen_start) * 1000
            total_ms = (time.monotonic() - start_time) * 1000
            _debug_log(f"generation_ms={gen_ms:.1f}")
            _debug_log(f"rag_total_ms={total_ms:.1f}")

        return {"context": context}, _timed_stream()
