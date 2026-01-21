"""LangGraph builder for the RAG agent."""

from __future__ import annotations

from src.graph.nodes.live_rag import live_rag_node
from src.graph.nodes.orchestrator import orchestrator_node
from src.graph.nodes.planner import planner_node
from src.graph.nodes.validator import validator_node
from src.graph.nodes.report import report_node
from src.graph.nodes.summarize import summarize_node
from src.graph.nodes.debug import debug_node
from src.graph.nodes.audit import audit_node
from src.graph.nodes.memory import memory_node
from src.graph.nodes.safety import safety_node
from src.graph.nodes.health_check import health_check_node
from src.graph.nodes.inventory import inventory_node
from src.graph.nodes.regression import regression_node
from src.graph.nodes.metrics import metrics_node
from src.graph.nodes.ingest import ingest_node
from src.graph.nodes.policy import policy_node
from src.graph.nodes.feedback import feedback_node
from src.graph.nodes.recovery import recovery_node
from src.graph.nodes.retrieval import retrieval_node
from src.graph.nodes.response import response_node
from src.graph.nodes.supervisor import supervisor_node
from src.graph.state import GraphState, coerce_state
from src.config import load_config
from src.agent.metrics import append_metric
from pathlib import Path
import time
from src.agent.feedback import append_feedback_log

from src.graph.nodes.critic import critic_node
from src.graph.nodes.scientist import scientist_node
from src.graph.nodes.correlation import correlation_node
from src.graph.nodes.drift import drift_node
from src.graph.nodes.triage import triage_node

def _route(state: GraphState | dict) -> str:
    """Return the next node based on the supervisor decision."""

    current = coerce_state(state)
    if current.route == "help":
        return "response"
    if current.route == "live_rag":
        return "live_rag"
    if current.route == "planner":
        return "planner"
    if current.route == "validator":
        return "validator"
    if current.route == "report":
        return "report"
    if current.route == "orchestrator":
        return "orchestrator"
    if current.route == "summarize":
        return "summarize"
    if current.route == "debug":
        return "debug"
    if current.route == "audit":
        return "audit"
    if current.route == "memory":
        return "memory"
    if current.route == "safety":
        return "safety"
    if current.route == "health":
        return "health"
    if current.route == "inventory":
        return "inventory"
    if current.route == "regression":
        return "regression"
    if current.route == "metrics":
        return "metrics"
    if current.route == "ingest":
        return "ingest"
    if current.route == "policy":
        return "policy"
    if current.route == "feedback":
        return "feedback"
    if current.route == "recovery":
        return "recovery"
        
    # Autonomy Routes
    if current.route == "critic":
        return "critic"
    if current.route == "scientist":
        return "scientist"
    if current.route == "correlation":
        return "correlation"
    if current.route == "drift":
        return "drift"
    if current.route == "triage":
        return "triage"
        
    return "retrieval"


def build_graph():
    """Build and compile the LangGraph flow."""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError(
            "langgraph is not installed. Install with: pip install langgraph"
        ) from exc

    graph = StateGraph(GraphState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("live_rag", live_rag_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("planner", planner_node)
    graph.add_node("validator", validator_node)
    graph.add_node("report", report_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("debug", debug_node)
    graph.add_node("audit", audit_node)
    graph.add_node("memory", memory_node)
    graph.add_node("safety", safety_node)
    graph.add_node("health", health_check_node)
    graph.add_node("inventory", inventory_node)
    graph.add_node("regression", regression_node)
    graph.add_node("metrics", metrics_node)
    graph.add_node("ingest", ingest_node)
    graph.add_node("policy", policy_node)
    graph.add_node("feedback", feedback_node)
    graph.add_node("recovery", recovery_node)
    graph.add_node("response", response_node)
    
    # New Autonomy Nodes
    graph.add_node("critic", critic_node)
    graph.add_node("scientist", scientist_node)
    graph.add_node("correlation", correlation_node)
    graph.add_node("drift", drift_node)
    graph.add_node("triage", triage_node)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route,
        {
            "retrieval": "retrieval",
            "live_rag": "live_rag",
            "planner": "planner",
            "validator": "validator",
            "report": "report",
            "orchestrator": "orchestrator",
            "summarize": "summarize",
            "debug": "debug",
            "audit": "audit",
            "memory": "memory",
            "safety": "safety",
            "health": "health",
            "inventory": "inventory",
            "regression": "regression",
            "metrics": "metrics",
            "ingest": "ingest",
            "policy": "policy",
            "feedback": "feedback",
            "recovery": "recovery",
            "response": "response",
            
            # Autonomy
            "critic": "critic",
            "scientist": "scientist",
            "correlation": "correlation",
            "drift": "drift",
            "triage": "triage",
        },
    )
    graph.add_edge("retrieval", "response")
    graph.add_edge("live_rag", "response")
    graph.add_edge("planner", "response")
    graph.add_edge("validator", "response")
    graph.add_edge("report", "response")
    graph.add_edge("orchestrator", "response")
    graph.add_edge("summarize", "response")
    graph.add_edge("debug", "response")
    graph.add_edge("audit", "response")
    graph.add_edge("memory", "response")
    graph.add_edge("safety", "response")
    graph.add_edge("health", "response")
    graph.add_edge("inventory", "response")
    graph.add_edge("regression", "response")
    graph.add_edge("metrics", "response")
    graph.add_edge("ingest", "response")
    graph.add_edge("policy", "response")
    graph.add_edge("feedback", "response")
    graph.add_edge("recovery", "response")
    
    # Autonomy Edges -> Response
    graph.add_edge("critic", "response")
    graph.add_edge("scientist", "response")
    graph.add_edge("correlation", "response")
    graph.add_edge("drift", "response")
    graph.add_edge("triage", "response")
    
    graph.add_edge("response", END)
    return graph.compile()


def run_graph(query: str, history: list[dict] | None = None, session_id: str | None = None) -> GraphState:
    """Run the LangGraph flow for a single query and return the final state."""

    graph = build_graph()
    start = time.monotonic()
    state = GraphState(query=query, history=history or [], session_id=session_id)
    result = graph.invoke(state)
    final_state = coerce_state(result)
    cfg = load_config()
    duration_ms = (time.monotonic() - start) * 1000.0
    if cfg.feedback_log_enabled:
        append_feedback_log(
            cfg.feedback_log_path,
            {
                "session_id": final_state.session_id,
                "query": query,
                "response": final_state.response,
                "route": final_state.route,
                "rag_mode": cfg.rag_mode,
                "rag_only": cfg.rag_only,
                "has_context": bool(final_state.context),
                "has_live_output": bool(final_state.last_live_output or final_state.last_live_summary),
            },
        )
    if cfg.metrics_enabled:
        append_metric(
            Path(cfg.metrics_path),
            {
                "ts": time.time(),
                "session_id": final_state.session_id,
                "route": final_state.route,
                "rag_mode": cfg.rag_mode,
                "duration_ms": round(duration_ms, 2),
                "query_len": len(query),
                "has_context": bool(final_state.context),
                "has_live_output": bool(final_state.last_live_output or final_state.last_live_summary),
            },
        )
    return final_state


def stream_run_graph(query: str, history: list[dict] | None = None, session_id: str | None = None):
    """Run the LangGraph flow and yield intermediate events."""

    graph = build_graph()
    start = time.monotonic()
    state = GraphState(query=query, history=history or [], session_id=session_id)
    
    final_state = None
    for event in graph.stream(state):
        yield event
        # Keep track of the latest state to log metrics at the end
        for value in event.values():
            if isinstance(value, dict):
                 # We need to reconstruct/coerce the state if possible, or just wait for the end
                 pass
            if isinstance(value, GraphState): # unlikely, usually dict
                 pass

    # Re-invoke to get final state for logging? 
    # Actually graph.stream yields updates. The state is accumulated.
    # To get the final state cleanly, we might need to recreate it from history or just rely on 'response' node output.
    # A cleaner way for logging is to just invoke it if we want full state, but that runs it twice.
    # Alternatively, we just return the final event's data.
    
    # But wait, checking how metrics are logged in run_graph:
    # It uses 'final_state' which is the result of invoke.
    
    # We can use the last event to determine the state, but it might be partial.
    # Simpler approach: We yield events, and the consumer handles UI. 
    # For metrics, we can't easily do it here without accumulating state.
    # Let's Skip metrics in stream_run_graph for now or try to approximate it.
    # Or better: The consumer (sena.py) can call a logging helper if needed.

