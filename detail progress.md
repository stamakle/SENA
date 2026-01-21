# Detailed Development Progress Report

## Overview
This report summarizes the initial local RAG development work based on the Beginner-Friendly Implementation Guide. It documents what was implemented, why each component exists, and shows key code snippets for beginners to understand the flow.

## What Was Built and Why

### 1) Configuration and Local Runtime
- File: `src/config.py`
- Reason: centralizes environment settings so the rest of the code is simple and consistent.

Snippet:
```python
@dataclass
class Config:
    """Runtime configuration values loaded from environment variables."""

    ollama_base_url: str
    chat_model: str
    embed_model: str
    pg_dsn: str
```

### 2) Ollama Client (Chat + Embeddings)
- File: `src/llm/ollama_client.py`
- Reason: keeps HTTP logic in one place and makes local LLM calls easy to reuse.

Snippet:
```python
# Step 5: Build the vector index (embeddings via Ollama).

def embed_text(base_url: str, model: str, text: str, timeout_sec: int) -> List[float]:
    """Return an embedding vector for the given text using Ollama."""

    url = f"{base_url}/api/embeddings"
    payload = {"model": model, "prompt": text}
```

### 3) Data Preparation (CSV/TSV -> JSONL)
- File: `src/ingest/prepare_data.py`
- Reason: normalizes raw files into clean JSONL records for indexing.

Snippet:
```python
# Step 2: Prepare the data.

def _build_test_cases(rows: Iterable[Dict[str, str]]) -> List[Dict[str, object]]:
    """Group test case rows into case-level records with ordered steps."""

    grouped: Dict[str, Dict[str, object]] = {}
    steps_by_case: Dict[str, List[Dict[str, str]]] = defaultdict(list)
```

### 4) Postgres Schema + Hybrid Indexes
- File: `src/db/postgres.py`
- Reason: stores structured fields and enables hybrid retrieval (BM25 + vector).

Snippet:
```python
# Step 3: Store structured data in Postgres.
# Step 4: Build the text search indexes.
# Step 5: Build the vector index.

def create_tables(conn, embed_dim: int) -> None:
    """Create tables and indexes needed for hybrid retrieval."""

    cur.execute("CREATE INDEX IF NOT EXISTS idx_test_cases_tsv ON test_cases USING GIN(tsv)")
```

### 5) Hybrid Retrieval Pipeline
- File: `src/retrieval/pipeline.py`
- Reason: combines keyword and vector search for stronger recall on mixed data.

Snippet:
```python
# Step 6: Create the retrieval function.

def hybrid_search(conn, query: str, embedding: List[float], filters: Dict[str, str], limit: int) -> List[Dict[str, Any]]:
    """Search test cases and system logs and return merged results."""

    results = []
    results.extend(_search_table(conn, "test_cases", query, embedding, filters, limit))
    results.extend(_search_table(conn, "system_logs", query, embedding, filters, limit))
```

### 6) Reranker Placeholder
- File: `src/retrieval/reranker.py`
- Reason: placeholder so you can swap in a local reranker later without changing the pipeline.

Snippet:
```python
# Step 7: Add reranking.

def rerank_results(query: str, chunks: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """Return the top K chunks in their current order."""
```

### 7) Context Builder
- File: `src/retrieval/context_builder.py`
- Reason: creates a compact context block with citations for the final answer.

Snippet:
```python
# Step 8: Build the answer context.

def build_context(chunks: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, str]]]:
    """Build a context string and simple citations list."""
```

### 8) TTL Cache
- File: `src/cache/ttl_cache.py`
- Reason: avoids repeated retrieval work for similar queries.

Snippet:
```python
# Step 10: Add caching.

class TTLCache:
    """In-memory cache with time-based expiration."""
```

### 9) SSH Execution Helper (Allowlist)
- File: `src/tools/ssh_client.py`
- Reason: enables safe live data queries while enforcing allowlists.

Snippet:
```python
# Step 10: Add SSH execution with allowlists.

def run_ssh_command(user: str, host: str, command: str, allowlist: Iterable[str], timeout_sec: int = 5) -> str:
    """Run an allowlisted SSH command and return stdout text."""
```

### 10) RAG Agent Integration for UI
- File: `agent.py`
- Reason: implements the interface expected by `ui_nicegui/sena.py` for streaming responses.

Snippet:
```python
# Step 9: Connect the UI to the agent pipeline.

class RAGSshAgent:
    """RAG agent that retrieves context and generates answers locally."""

    def prepare_streaming_prompt(self, question: str, system_prompt: str, history: List[Dict[str, str]] | None = None):
        """Prepare context and return a generator for streaming output."""
```

### 11) System Prompt
- File: `prompt.py`
- Reason: a minimal system instruction for consistent, grounded answers.

Snippet:
```python
SYSTEM_PROMPT = (
    "You are a local RAG assistant. Answer using the provided context only."
)
```

### 12) LangGraph Core Scaffolding (Phase 1)
- Files: `src/graph/state.py`, `src/graph/graph.py`, `src/graph/nodes/*.py`
- Reason: establishes a typed state schema and a supervisor-worker graph to orchestrate multi-agent routing.

Snippet:
```python
# Step 12: LangGraph core wiring.

graph = StateGraph(GraphState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("retrieval", retrieval_node)
graph.add_node("response", response_node)
```

### 13) UI Wired to LangGraph (Phase 1 Extension)
- File: `ui_nicegui/sena.py`
- Reason: routes chat requests through the LangGraph pipeline while keeping session summaries updated.

Snippet:
```python
result = await asyncio.to_thread(run_graph, msg, history=hist, session_id=session_id)
for chunk in _chunk_text(result.response):
    accumulated += chunk
```

### 14) Live-RAG (SSH) Node (Phase 2)
- Files: `src/graph/nodes/live_rag.py`, `src/graph/nodes/supervisor.py`, `src/graph/graph.py`
- Reason: enables controlled SSH execution from the graph with allowlist enforcement and safe parsing.

Snippet:
```python
graph.add_node("live_rag", live_rag_node)
graph.add_edge("live_rag", "response")
```

### 15) Live-RAG Session Memory + Follow-Up Handling
- Files: `src/agent/live_memory.py`, `src/graph/state.py`, `src/graph/nodes/live_rag.py`, `src/graph/nodes/response.py`
- Reason: preserves live SSH output for follow-up questions like “what errors are in this output.”

Snippet:
```python
set_live_entry(live_path, current.session_id, output, "")
```

### 16) Phase 4 — Custom Live Command Registry (JSON)
- Files: `configs/live_commands.json`, `src/graph/nodes/live_rag.py`, `configs/ssh.json`
- Reason: lets you register custom `/live` commands in a JSON file and execute them safely via the allowlist.

Snippet:
```json
{
  "commands": [
    {
      "name": "nvme-fwlog",
      "command": "nvme fw-log /dev/nvme0",
      "aliases": ["fwlog", "nvme fw-log", "nvme-fw-log"],
      "summary_default": false,
      "description": "Read NVMe firmware log page from /dev/nvme0"
    }
  ]
}
```

Example usage:
- `/live nvme-fwlog <hostname|service_tag>`

### 17) Phase 4 Extension — Human-in-the-Loop Command Approval
- Files: `src/graph/nodes/live_rag.py`, `configs/live_commands_pending.json`, `configs/live_commands.json`, `configs/ssh.json`
- Reason: blocks unallowlisted commands, queues them for approval, and updates the registry + allowlist only after human approval.

Example flow:
- Run unknown command → queued with `/live pending`
- Approve → `/live approve <name>` updates registry + allowlist

### 18) Feedback Logs for Prompt Tuning
- Files: `src/agent/feedback.py`, `src/graph/graph.py`, `src/config.py`
- Reason: appends a JSONL log of prompts + responses for later prompt tuning and analysis.

Default log path:
- `logs/feedback.jsonl`

### 19) Multi-Agent Expansion Nodes (Planner + Summary + Debug + Audit + Memory + Safety)
- Files: `src/graph/nodes/summarize.py`, `src/graph/nodes/debug.py`, `src/graph/nodes/audit.py`, `src/graph/nodes/memory.py`, `src/graph/nodes/safety.py`, `src/graph/graph.py`, `src/graph/nodes/supervisor.py`
- Reason: adds explicit multi-agent roles (summarizer, debugger, auditor, memory, safety/approval) and routes them through LangGraph.

Snippet:
```python
graph.add_node("summarize", summarize_node)
graph.add_node("debug", debug_node)
graph.add_node("audit", audit_node)
graph.add_node("memory", memory_node)
graph.add_node("safety", safety_node)
```

### 20) Audit Pipeline (Deterministic + LLM Analysis)
- File: `src/agent/audit_pipeline.py`
- Reason: supports post-run audits from an arbitrary log path with deterministic step matching plus LLM analysis.

Snippet:
```python
def run_audit_pipeline(query: str) -> str:
    # load logs from path, audit steps, summarize + bundle
```

### 21) Health Check Agent
- File: `src/graph/nodes/health_check.py`
- Reason: validates SSH reachability and sudo readiness before live ops.

Snippet:
```python
run_ssh_command(host, "sudo -n true", cfg.ssh_config_path)
```

### 22) Inventory Agent
- File: `src/graph/nodes/inventory.py`
- Reason: provides NVMe inventory by host or rack (reuses rack scan logic).

Snippet:
```python
output = run_ssh_command(host, "nvme list", cfg.ssh_config_path)
```

### 23) Regression Monitor
- Files: `src/agent/regression_monitor.py`, `src/graph/nodes/regression.py`
- Reason: compares recent testcase runs to flag pass→fail regressions.

### 24) Metrics Agent
- Files: `src/agent/metrics.py`, `src/graph/nodes/metrics.py`, `src/graph/graph.py`
- Reason: logs per‑query latency + routes and exposes summary stats.

### 25) Data Ingest Agent
- File: `src/graph/nodes/ingest.py`
- Reason: lists new CSV/XLSX files and can run ingestion scripts on request.

### 26) Policy Agent
- File: `src/graph/nodes/policy.py`
- Reason: surfaces guardrails (RAG mode, strict/auto, allowlist counts).

### 27) Feedback Agent
- File: `src/graph/nodes/feedback.py`
- Reason: summarizes prompt/response feedback logs for tuning.

### 28) Recovery Agent
- File: `src/graph/nodes/recovery.py`
- Reason: suggests safe fallbacks based on recent live failures.

### 29) Model Router
- File: `src/agent/model_router.py`
- Reason: selects smaller vs larger local models for speed/quality balance.

### 19) Phase 5 — Context Engineering & Guardrails
- Files: `src/config.py`, `src/graph/nodes/response.py`, `ui_nicegui/sena.py`
- Reason: supports automatic RAG/general routing, evidence-based headers, and UI controls for RAG mode.

Highlights:
- RAG mode auto/strict/general toggle in UI drawer.
- Evidence-based vs General knowledge headers added.
- “Needs evidence” responses include next-step suggestions.

### 20) Phase 6 — Multi-Agent Expansion (Planner/Validator/Report)
- Files: `src/graph/nodes/planner.py`, `src/graph/nodes/validator.py`, `src/graph/nodes/report.py`, `src/graph/graph.py`, `src/graph/nodes/supervisor.py`
- Reason: introduces explicit planning, validation, and reporting nodes for SSD validation workflows.

Usage:
- `/plan ...` → planner node
- `/validate ...` → validator node
- `/report ...` → report node

### 21) Phase 7 — Prompt Regression Tests
- Files: `tests/test_prompts.py`, `scripts/run_prompt_tests.sh`
- Reason: basic automated checks for RAG, general knowledge, and planner routes.

Run:
- `bash scripts/run_prompt_tests.sh`

### 22) Phase 8 — UI Enhancements
- Files: `ui_nicegui/sena.py`
- Reason: adds live command list panel and mode badges (RAG mode, live mode, strict/auto).

### 23) Phase 9 — Reliability & Performance
- Files: `src/agent/live_cache.py`, `src/graph/nodes/live_rag.py`, `src/config.py`, `ui_nicegui/sena.py`
- Reason: adds live output caching (TTL), retry control, and UI timeout settings.

### 16) Live Output Summary + Toggle + /live Command
- Files: `src/agent/summary_live.py`, `src/config.py`, `src/graph/nodes/live_rag.py`, `src/graph/nodes/response.py`
- Reason: summarizes SSH output, supports summary-only mode, and allows explicit `/live last` retrieval.

Snippet:
```python
summary = summarize_live_output(output, ...)
```

### 17) Live Output Controls (Clear/Cap/Error Extract)
- Files: `src/agent/live_memory.py`, `src/agent/live_extract.py`, `src/config.py`, `src/graph/nodes/live_rag.py`, `src/graph/nodes/response.py`
- Reason: caps stored output size, adds `/live clear` and `/live errors`, and exposes a generic error extractor for follow-ups.

### 18) Live-RAG Auto-Sudo Handling
- Files: `src/graph/nodes/live_rag.py`, `src/tools/ssh_client.py`
- Reason: automatically prefixes sudo for live commands and accepts sudo-prefixed allowlist checks.

### 19) Live-RAG Sudo Password Fallback
- Files: `src/tools/ssh_client.py`, `src/graph/nodes/live_rag.py`
- Reason: uses `sudo -n` by default and retries with `sudo -S` when a password is required.

### 20) SSH Hostname Fallback to IP
- File: `src/tools/ssh_client.py`
- Reason: attempts hostname first and falls back to resolved IP if hostname fails.

### 21) Live-RAG Sudo Check Command
- Files: `src/graph/nodes/live_rag.py`, `src/graph/nodes/response.py`
- Reason: `/live sudo-check <host>` runs a safe sudo probe and reports access.

### 22) Live Dmesg Shortcut + Sudo Status UI
- Files: `src/graph/nodes/live_rag.py`, `ui_nicegui/sena.py`, `src/agent/live_memory.py`
- Reason: adds `/live dmesg <host>` and surfaces sudo status in the UI header.

### 23) Live Output Summary Guardrails
- File: `src/graph/nodes/live_rag.py`
- Reason: prevents chatty/hallucinated summaries by requiring grounded overlap and minimum output size.

### 24) Live-RAG Deterministic Mode + Shortcuts
- Files: `src/graph/nodes/live_rag.py`, `src/config.py`, `src/agent/live_memory.py`, `configs/ssh.json`
- Reason: adds strict command templates, per-session strict toggle, and more `/live` shortcuts.

### 25) Fast NVMe Follow-up Handler
- File: `src/graph/nodes/response.py`
- Reason: handles “more details” and NVMe filtering on the last live lspci output without calling the LLM.

### 26) Deterministic PCI ID Expansion
- Files: `src/agent/pci_lookup.py`, `src/graph/nodes/response.py`
- Reason: expands PCI vendor/device IDs using a local lookup table.

### 27) Live-RAG Auto-Execute + Strict/Flexible Mode
- Files: `src/config.py`, `src/agent/live_memory.py`, `src/graph/nodes/live_rag.py`
- Reason: adds auto-execute toggle with pending execution and strict template enforcement.

## Current Status
- Data preparation script exists but not run yet.
- Postgres schema helper exists but not executed.
- Hybrid retrieval, caching, and agent integration are ready for first local test.

## Known Gaps
- Reranker is a placeholder (no scoring model yet).
- No SQL filter extraction or advanced query rewriting yet.
- No automated indexing script; manual steps are required initially.

## Immediate Next Steps
- Run the data prep script and confirm `data/processed/*.jsonl` outputs.
- Set up Postgres with pgvector and load data into the tables.
- Run the UI and validate responses with small test queries.

## Phase 10 — Tool Orchestration (Testcases + Firmware)
- Files: `src/graph/nodes/orchestrator.py`, `src/agent/testcase_registry.py`, `src/agent/debug_agent.py`, `src/tools/ssh_client.py`, `ui_nicegui/sena.py`
- Reason: adds multi-step orchestration for testcase execution, log collection, analysis, and bundle download links. Adds firmware update tool runner (dry-run by default).

Implemented:
- Testcase runner: uploads script to target, executes, captures stdout/stderr.
- Log collector: dmesg, journalctl, lspci, nvme list, nvme smart/error logs.
- Debug analysis: always-on LLM analysis for both pass and fail.
- Bundle export: tar.gz artifact bundle with UI download link.
- Registry: auto-detect scripts in `data/custom_tools/testcase_scripts` for future additions.

Integration steps for new scripts:
1) Drop script into `data/custom_tools/testcase_scripts` (name must include `TC-####` or `DSSTC-####`).
2) If the script needs extra args (e.g., device), include them in the prompt:
   - `Run testcase DSSTC-5351 on host 98HLZ85 device /dev/nvme0n1`
3) If the script depends on extra binaries (e.g., `msecli`), place them beside the script and ensure they exist on the target host.
4) First run auto-adds an allowlisted command in `configs/ssh.json` for the script.
5) Bundle output will be saved under `data/exports/bundles` and linked in the UI.
