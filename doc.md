# Agent Graph Specification (LangGraph + Hierarchical Multi-Agent)

## Explanation and Rationale

This design uses LangGraph with a supervisor-worker structure to keep routing deterministic, debuggable, and cost-aware while enabling specialist agents for retrieval, SQL lookups, and tool execution. The dataset mixes structured fields (IDs, rack/slot, model, versions) with long-form steps and descriptions, so a hybrid flow is required. The graph separates intent detection, retrieval, reranking, and context assembly to maximize precision and make failures traceable.

## Recommended Stack

- Primary (locked): Postgres 15 + `pgvector` for embeddings + `tsvector` (GIN) for BM25-style lexical search.
- LLM runtime: Ollama (local) for generation; choose a local model that fits hardware (for example: Llama 3.1, Mistral).
- Embeddings: Ollama embedding model (for example: `nomic-embed-text` or `mxbai-embed-large`), store vectors in Postgres.
- Reranking: local reranker (for example: `bge-reranker`) or an LLM reranker via Ollama if available.
- Ingestion: Python with Polars or DuckDB for robust CSV/TSV handling and normalization.
- Deployment: all services run locally (no external APIs).

## Semantic Search Recommendation

Yes. Use semantic search for descriptions, test steps, and free-form logs with local embeddings, and combine it with lexical search for IDs, model numbers, and BIOS versions. A hybrid retriever (semantic + BM25) with reranking consistently improves recall and precision on this dataset.

## Latency + Quality Strategy (Proceed With Both)

- Use a 7B-class local model for final answers and a small model for routing/rewrites to keep latency reasonable on CPU.
- Add retrieval caching (per-query + per-filter key) with short TTL to reduce repeated vector/BM25 hits.
- Keep a local reranker enabled to improve precision on similar or repetitive test steps.
- Cache reranker results by query + chunk IDs to avoid re-scoring in follow-up turns.
- Favor structured SQL lookups when filters are explicit to avoid unnecessary model calls.

## Beginner-Friendly Implementation Guide

This is a simple, step-by-step way to build the system locally using Ollama and Postgres.

### Step 1: Run local services

- Start Ollama locally for chat and embeddings.
- Start Postgres with `pgvector` enabled.

### Step 2: Prepare the data

- Read the CSV/TSV files and clean them (fix multiline fields, remove empty rows).
- Create two outputs:
  - `test_cases.jsonl` with one record per test case (include steps).
  - `system_logs.jsonl` with one record per host or system.

### Step 3: Store structured data in Postgres

- Create tables for test cases and system logs.
- Insert the cleaned records.

### Step 4: Build the text search indexes

- Add `tsvector` columns for full-text search.
- Create a GIN index for fast keyword search.

### Step 5: Build the vector index

- Call Ollama embeddings for each record.
- Store the vectors in `pgvector` columns.

### Step 6: Create the retrieval function

- When a user asks a question:
  - Extract filters (example: rack, model, test case ID).
  - Run BM25 (keyword) search and vector search.
  - Merge the results and keep the top N.

### Step 7: Add reranking

- Send the top N results to a local reranker.
- Keep the best K chunks for the final answer.

### Step 8: Build the answer context

- Concatenate the best chunks with short citations.
- Send the context + question to the chat model in Ollama.

### Step 9: Connect the UI

- Implement the `agent.RAGSshAgent` interface used by `ui_nicegui/sena.py`.
- Stream the answer back to the UI.

### Step 10: Add caching and SSH (optional)

- Cache retrieval results by query + filters for a short TTL.
- If SSH is enabled, only allow approved commands and admin users.

## Nodes

| Node ID | Role | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| N1 | Intake | Normalize request, attach session metadata | user_query, session_id | normalized_query |
| N2 | Memory | Load short-term turns + summary | session_id | history, memory_summary |
| N3 | IntentRouter | Classify request and choose path | normalized_query, history | intent, route |
| N4 | QueryRewrite | Rewrite with context for retrieval | normalized_query, history, memory_summary | search_query |
| N5 | Planner | Create steps, tool plan, and stop criteria | normalized_query, intent | plan |
| N6 | RetrievalAgent | Hybrid retrieval over test cases/logs | search_query, filters | retrieval_results |
| N7 | SQLAgent | Exact structured lookup | filters, intent | sql_results |
| N8 | Reranker | Rerank and dedupe candidates | retrieval_results, sql_results | ranked_chunks |
| N9 | ContextBuilder | Build context with citations | ranked_chunks, plan | context, citations |
| N10 | Guardrail | Redact sensitive data, policy checks | context, citations | safe_context, redaction_flags |
| N11 | Generator | Produce final answer | safe_context, normalized_query | answer |
| N12 | DebugTrace | Emit trace and explanations | state | trace_report |
| N13 | ExecutionAgent | Run safe, allowed tools when needed | plan, tool_calls | tool_outputs |

## Edges

| From | To | Condition |
|---|---|---|
| N1 | N2 | always |
| N2 | N3 | always |
| N3 | N5 | always |
| N3 | N4 | route includes retrieval |
| N4 | N6 | route includes retrieval |
| N3 | N7 | route includes structured lookup |
| N5 | N13 | plan requires tools |
| N6 | N8 | retrieval_results available |
| N7 | N8 | sql_results available |
| N8 | N9 | ranked_chunks available |
| N9 | N10 | always |
| N10 | N11 | always |
| N11 | N12 | debug or audit enabled |

## State Schema

| Field | Type | Description |
|---|---|---|
| session_id | string | Conversation/session identifier |
| user_query | string | Raw user input |
| normalized_query | string | Cleaned and normalized user input |
| history | list[message] | Recent turns used for grounding |
| memory_summary | string | Compressed long-term memory |
| intent | string | Query type label |
| route | list[string] | Selected path(s) |
| filters | dict | Structured filters extracted from query |
| plan | list[string] | Task steps and stop criteria |
| search_query | string | Retrieval-optimized query |
| retrieval_results | list[chunk] | Hybrid retrieval candidates |
| sql_results | list[row] | Structured lookup results |
| ranked_chunks | list[chunk] | Reranked context chunks |
| citations | list[citation] | Source references for responses |
| context | string | Assembled context block |
| safe_context | string | Redacted/approved context |
| redaction_flags | list[string] | Policy violations detected |
| tool_calls | list[tool_call] | Planned tool invocations |
| tool_outputs | list[tool_output] | Results from tools |
| answer | string | Final response text |
| trace_report | string | Debug trace for inspection |
| metrics | dict | Retrieval and response metrics |
| errors | list[string] | Captured failure messages |

## Agent-to-Tool and Data Mapping

| Agent | Tools | Data Sources | Notes |
|---|---|---|---|
| RetrievalAgent | Postgres (`pgvector` + `tsvector`) | `/home/aseda/project/sena_try/data/processed/test_cases.jsonl`, `/home/aseda/project/sena_try/data/processed/system_logs.jsonl` | Hybrid recall for descriptions and steps |
| SQLAgent | Postgres (read-only queries) | `/home/aseda/project/sena_try/data/processed/*.parquet` | Exact filters on IDs, rack, model, versions |
| Reranker | Cross-encoder or LLM rerank | candidate chunks | Improves precision on similar test steps |
| ContextBuilder | Template packer, citation builder | ranked chunks | Ensures ordered steps and traceable answers |
| Guardrail | Redaction/policy checker | context | Removes credentials, IPs, secrets |
| ExecutionAgent | Allowlisted scripts, read-only shell, SSH command runner | live systems or APIs | Optional, for diagnostics or structured tasks |
| DebugTrace | Trace formatter | state | Explains retrieval path and scoring |

## Live RAG via SSH (ExecutionAgent)

- Route: IntentRouter marks a request as live-system; Planner creates a tool plan; Supervisor approves before ExecutionAgent runs.
- Controls: command templates only, per-host allowlist, timeouts, stdout size caps, and redaction before response.
- Permissions: ExecutionAgent requires admin role; all tool calls logged and traceable.
- Caching: short TTL cache for repeated live queries to reduce load and latency.

## SSH Command Templates (Examples)

```
ssh {user}@{host} "uname -a"
ssh {user}@{host} "lscpu"
ssh {user}@{host} "lsblk -o NAME,SIZE,MODEL,SERIAL"
ssh {user}@{host} "lspci -nn"
ssh {user}@{host} "cat /etc/os-release"
ssh {user}@{host} "ip -4 addr show"
```

## SSH Allowlist Example (Policy)

```
{
  "allowed_commands": [
    "uname -a",
    "lscpu",
    "lsblk -o NAME,SIZE,MODEL,SERIAL",
    "lspci -nn",
    "cat /etc/os-release",
    "ip -4 addr show"
  ],
  "allowed_hosts": [
    "10.148.76.242",
    "10.148.76.246"
  ],
  "command_timeout_sec": 5,
  "max_output_bytes": 20000,
  "denylist_regex": [
    "rm\\s",
    "mkfs",
    "dd\\s",
    "reboot",
    "shutdown",
    "useradd",
    "apt\\s",
    "yum\\s"
  ]
}
```

## Role Hierarchy and Permissions

- Manager: sets policy, cost limits, allowed tools, and data boundaries.
- Supervisor: chooses route, approves tool execution, and enforces guardrails.
- Leads: Retrieval Lead, SQL Lead, Memory Lead, Guardrail Lead, Execution Lead, Response Lead.
- Workers: Retriever, SQL Query, Reranker, Context Builder, Redaction, SSH Execution, Trace/Debug.
- SSH Ownership: Execution Lead + SSH Execution Worker; requires admin role and Supervisor approval.

## LangGraph State Schema (Pydantic Models)

```python
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Message(BaseModel):
    role: str
    content: str

class Chunk(BaseModel):
    id: str
    text: str
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Citation(BaseModel):
    source: str
    chunk_id: Optional[str] = None
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ToolCall(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)

class ToolOutput(BaseModel):
    tool: str
    ok: bool
    output: str

class GraphState(BaseModel):
    session_id: Optional[str] = None
    user_query: Optional[str] = None
    normalized_query: Optional[str] = None
    history: List[Message] = Field(default_factory=list)
    memory_summary: Optional[str] = None
    intent: Optional[str] = None
    route: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    plan: List[str] = Field(default_factory=list)
    search_query: Optional[str] = None
    retrieval_results: List[Chunk] = Field(default_factory=list)
    sql_results: List[Dict[str, Any]] = Field(default_factory=list)
    ranked_chunks: List[Chunk] = Field(default_factory=list)
    citations: List[Citation] = Field(default_factory=list)
    context: Optional[str] = None
    safe_context: Optional[str] = None
    redaction_flags: List[str] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_outputs: List[ToolOutput] = Field(default_factory=list)
    answer: Optional[str] = None
    trace_report: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
```

## Implementation Notes

The graph is hierarchical with N3 (IntentRouter) and N5 (Planner) acting as supervisors that gate tool usage and select specialists. This keeps latency and costs predictable while allowing multi-agent collaboration only when needed. LangGraph adds determinism, state visibility, and retry semantics, which are important for debugging retrieval failures and maintaining stability as data grows.
