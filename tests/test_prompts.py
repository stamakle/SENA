"""Basic prompt regression checks."""

from __future__ import annotations

import os
import socket
import pytest

from src.graph.graph import run_graph
from src.db.postgres import get_connection


def _db_available() -> bool:
    dsn = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/sena")
    try:
        conn = get_connection(dsn)
        conn.close()
        return True
    except Exception:
        return False


def _ollama_available() -> bool:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    try:
        host = base_url.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
        port = int(base_url.split(":")[-1])
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


def _skip_if_unavailable():
    if not _db_available():
        pytest.skip("Postgres is not available for integration tests.")
    if not _ollama_available():
        pytest.skip("Ollama is not available for integration tests.")


def test_basic_rag_prompt():
    _skip_if_unavailable()
    result = run_graph("List test case TC-15174")
    assert result.response


def test_general_knowledge_prompt():
    _skip_if_unavailable()
    result = run_graph("What is wear leveling in SSDs?")
    assert result.response


def test_plan_command():
    _skip_if_unavailable()
    result = run_graph("/plan Outline SSD validation steps")
    assert "Proposed Plan" in result.response


def test_conversation_followup_rack_d1():
    _skip_if_unavailable()
    session_id = "test-session-d1"
    first = run_graph("List hosts in rack D1", session_id=session_id)
    assert first.response
    followup = run_graph("What errors are in this output?", session_id=session_id)
    assert followup.response
