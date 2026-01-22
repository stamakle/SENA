# SENA
SENA is a local, autonomous SSD validation agent that blends hybrid RAG with safe SSH tooling for NVMe diagnostics, test execution, and firmware triage.

## Quick start
- Ensure Postgres and Ollama are running.
- Run `scripts/launch_ui.sh` (bootstraps the search index from `data/` on first run).
- Set `SENA_BOOTSTRAP_SEARCH=0` to skip auto-indexing.

## Data
Dataset files under `data/` are versioned for portability; `.env` files remain ignored.
