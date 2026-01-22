"""Typed LangGraph state models.

These models define the shared state passed between graph nodes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Step 12: LangGraph state schema (Pydantic).


class PlanStep(BaseModel):
    """Structured plan step for execution."""

    step_id: str
    host_selector: str
    command: str
    preconditions: List[str] = Field(default_factory=list)
    expected_signals: List[str] = Field(default_factory=list)
    risk: str = "low"
    rollback: str = ""
    verify_command: Optional[str] = None


class ToolRequest(BaseModel):
    """Represents a tool request issued by the graph."""

    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    # P1 #15: Tool chaining support - reference previous tool result
    depends_on: Optional[str] = None  # ID of prior ToolRequest to chain from
    request_id: Optional[str] = None  # Unique ID for this request


class ToolResult(BaseModel):
    """Represents a tool execution result."""

    name: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_sec: Optional[float] = None
    host: Optional[str] = None
    command: Optional[str] = None
    error: Optional[str] = None
    # P1 #14: Structured error taxonomy
    error_code: Optional[str] = None
    error_class: Optional[str] = None
    recoverable: bool = True
    request_id: Optional[str] = None  # Links back to ToolRequest


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
    plan_steps: List[PlanStep] = Field(default_factory=list)
    critique: str = ""
    critique_status: str = ""
    hypothesis: str = ""
    observations: str = ""
    tool_requests: List[ToolRequest] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    last_live_output: str = ""
    last_live_summary: str = ""
    debug: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    role_assignment: Dict[str, Any] = Field(default_factory=dict)
    
    # P1 #2: Goal decomposition tracking
    goal_tracker: Dict[str, Any] = Field(default_factory=dict)
    
    # P1 #21: Checkpointing for long-running tasks
    checkpoint: Optional[str] = None
    iteration_count: int = 0
    max_iterations: int = 10


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
