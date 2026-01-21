"""Configuration helpers for the local RAG system.

This module centralizes environment-driven settings so the rest of the code
can stay simple and beginner-friendly.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass


# Step 1: Local services configuration.


@dataclass
class Config:
    """Runtime configuration values loaded from environment variables."""

    ollama_base_url: str
    chat_model: str
    chat_small_model: str
    chat_fast_model: str
    tool_picker_model: str
    embed_model: str
    pg_dsn: str
    embed_dim: int
    cache_ttl_sec: int
    reranker_model: str
    top_k_bm25: int
    top_k_vector: int
    top_k_rerank: int
    max_context_chunks: int
    max_context_chars: int
    summary_enabled: bool
    summary_model: str
    summary_max_tokens: int
    summary_trigger_chars: int
    summary_mode: str
    summary_min_messages: int
    summary_update_every: int
    ssh_config_path: str
    chat_max_tokens: int
    request_timeout_sec: int
    live_output_mode: str
    live_summary_enabled: bool
    live_summary_model: str
    live_summary_max_tokens: int
    live_output_max_chars: int
    live_error_max_lines: int
    live_strict_mode: bool
    live_auto_execute: bool
    rag_only: bool
    rag_mode: str
    feedback_log_enabled: bool
    feedback_log_path: str
    live_cache_ttl_sec: int
    live_retry_count: int
    live_rack_timeout_sec: int
    live_rack_failure_ttl_sec: int
    live_rack_max_workers: int
    metrics_enabled: bool
    metrics_path: str


def load_config() -> Config:
    """Load configuration from environment variables with safe defaults."""

    return Config(
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        chat_model=os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b-instruct"),
        chat_small_model=os.getenv("OLLAMA_CHAT_SMALL_MODEL", "nemotron-mini:4b"),
        chat_fast_model=os.getenv("OLLAMA_CHAT_FAST_MODEL", "qwen2.5:1.5b"),
        tool_picker_model=os.getenv("OLLAMA_TOOL_PICKER_MODEL", "functiongemma"),
        embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        pg_dsn=os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/sena"),
        embed_dim=int(os.getenv("EMBED_DIM", "768")),
        cache_ttl_sec=int(os.getenv("CACHE_TTL_SEC", "60")),
        reranker_model=os.getenv("RERANKER_MODEL", "bge-reranker"),
        top_k_bm25=int(os.getenv("TOP_K_BM25", "20")),
        top_k_vector=int(os.getenv("TOP_K_VECTOR", "20")),
        top_k_rerank=int(os.getenv("TOP_K_RERANK", "8")),
        max_context_chunks=int(os.getenv("MAX_CONTEXT_CHUNKS", "8")),
        max_context_chars=int(os.getenv("MAX_CONTEXT_CHARS", "4000")),
        summary_enabled=os.getenv("SUMMARY_ENABLED", "true").lower() in {"1", "true", "yes"},
        summary_model=os.getenv("SUMMARY_MODEL", os.getenv("OLLAMA_CHAT_SMALL_MODEL", "nemotron-mini:4b")),
        summary_max_tokens=int(os.getenv("SUMMARY_MAX_TOKENS", "160")),
        summary_trigger_chars=int(os.getenv("SUMMARY_TRIGGER_CHARS", "1800")),
        summary_mode=os.getenv("SUMMARY_MODE", "summary_only"),
        summary_min_messages=int(os.getenv("SUMMARY_MIN_MESSAGES", "6")),
        summary_update_every=int(os.getenv("SUMMARY_UPDATE_EVERY", "6")),
        ssh_config_path=os.getenv("SENA_SSH_CONFIG", "configs/ssh.json"),
        chat_max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "1024")),
        request_timeout_sec=int(os.getenv("REQUEST_TIMEOUT_SEC", "60")),
        live_output_mode=os.getenv("LIVE_OUTPUT_MODE", "full"),
        live_summary_enabled=os.getenv("LIVE_SUMMARY_ENABLED", "true").lower() in {"1", "true", "yes"},
        live_summary_model=os.getenv("LIVE_SUMMARY_MODEL", os.getenv("SUMMARY_MODEL", "nemotron-mini:4b")),
        live_summary_max_tokens=int(os.getenv("LIVE_SUMMARY_MAX_TOKENS", "160")),
        live_output_max_chars=int(os.getenv("LIVE_OUTPUT_MAX_CHARS", "12000")),
        live_error_max_lines=int(os.getenv("LIVE_ERROR_MAX_LINES", "50")),
        live_strict_mode=os.getenv("LIVE_STRICT_MODE", "false").lower() in {"1", "true", "yes"},
        live_auto_execute=os.getenv("LIVE_AUTO_EXECUTE", "true").lower() in {"1", "true", "yes"},
        rag_only=os.getenv("RAG_ONLY", "false").lower() in {"1", "true", "yes"},
        rag_mode=os.getenv("RAG_MODE", "auto"),
        feedback_log_enabled=os.getenv("FEEDBACK_LOG_ENABLED", "true").lower() in {"1", "true", "yes"},
        feedback_log_path=os.getenv(
            "FEEDBACK_LOG_PATH",
            str(Path(__file__).resolve().parents[2] / "logs" / "feedback.jsonl"),
        ),
        live_cache_ttl_sec=int(os.getenv("LIVE_CACHE_TTL_SEC", "30")),
        live_retry_count=int(os.getenv("LIVE_RETRY_COUNT", "1")),
        live_rack_timeout_sec=int(os.getenv("LIVE_RACK_TIMEOUT_SEC", "8")),
        live_rack_failure_ttl_sec=int(os.getenv("LIVE_RACK_FAILURE_TTL_SEC", "600")),
        live_rack_max_workers=int(os.getenv("LIVE_RACK_MAX_WORKERS", "4")),
        metrics_enabled=os.getenv("METRICS_ENABLED", "true").lower() in {"1", "true", "yes"},
        metrics_path=os.getenv(
            "METRICS_PATH",
            str(Path(__file__).resolve().parents[2] / "logs" / "graph_metrics.jsonl"),
        ),
    )
