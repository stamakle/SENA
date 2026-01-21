"""Basic prompt regression checks."""

from __future__ import annotations

from src.graph.graph import run_graph


def test_basic_rag_prompt():
    result = run_graph("List test case TC-15174")
    assert result.response


def test_general_knowledge_prompt():
    result = run_graph("What is wear leveling in SSDs?")
    assert result.response


def test_plan_command():
    result = run_graph("/plan Outline SSD validation steps")
    assert "Proposed plan" in result.response
