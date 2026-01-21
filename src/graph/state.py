"""Typed LangGraph state models.

These models define the shared state passed between graph nodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Step 12: LangGraph state schema (Pydantic).


class ToolRequest(BaseModel):
    """Represents a tool request issued by the graph."""

    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Represents a tool execution result."""

    name: str
    output: str = ""
    error: Optional[str] = None


class GraphState(BaseModel):
    """State object for the LangGraph orchestration layer."""

    query: str
    session_id: Optional[str] = None
    history: List[Dict[str, str]] = Field(default_factory=list)
    augmented_query: str = ""
    route: str = "rag"
    filters: Dict[str, str] = Field(default_factory=dict)
    tables: List[str] = Field(default_factory=list)
    step_mode: str = "summary"
    context: str = ""
    citations: List[Dict[str, str]] = Field(default_factory=list)
    response: str = ""
    plan: str = ""
    critique: str = ""
    hypothesis: str = ""
    observations: str = ""
    tool_requests: List[ToolRequest] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    last_live_output: str = ""
    last_live_summary: str = ""
    debug: List[str] = Field(default_factory=list)
    error: Optional[str] = None


def _model_dump(model: BaseModel) -> Dict[str, Any]:
    """Return a dict regardless of Pydantic version."""

    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def coerce_state(state: GraphState | Dict[str, Any]) -> GraphState:
    """Coerce a dict into GraphState for node implementations."""

    if isinstance(state, GraphState):
        return state
    if hasattr(GraphState, "model_validate"):
        return GraphState.model_validate(state)
    return GraphState.parse_obj(state)


def state_to_dict(state: GraphState) -> Dict[str, Any]:
    """Convert GraphState into a dict for LangGraph."""

    return _model_dump(state)
