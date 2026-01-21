# SENA Project - Setup Guide

This guide covers setting up the SENA RAG application on a new system, including database configuration, environment setup, and data indexing.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Database Configuration](#database-configuration)
4. [Environment Variables](#environment-variables)
5. [Setup Script Reference](#setup-script-reference)
6. [Data Indexing](#data-indexing)
7. [Start the Agent](#start-the-agent)
8. [Sample Prompts](#sample-prompts)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd sena_try

# 2. Run the setup script
./scripts/setup.sh

# 3. Source environment and start the app
source .env
.venv/bin/python ui_nicegui/sena.py
```

---

## Prerequisites

### Required Software

| Software | Version | Installation |
|----------|---------|--------------|
| Python | 3.10+ | `sudo apt install python3` |
| PostgreSQL | 14+ | `sudo apt install postgresql postgresql-contrib` |
| Ollama | Latest | `curl -fsSL https://ollama.com/install.sh \| sh` |

### Optional

| Software | Purpose |
|----------|---------|
| pgvector | Vector similarity search |
| CUDA | GPU acceleration for Ollama |

---

## Database Configuration

### Default Credentials

| Setting | Default Value |
|---------|---------------|
| **User** | `postgres` |
| **Password** | `postgres` |
| **Host** | `localhost` |
| **Port** | `5432` |
| **Database** | `sena` |

### Connection String (DSN)

The default connection string is:

```
postgresql://postgres:postgres@localhost:5432/sena
```

### Where Credentials Are Configured

1. **Code Default** (`src/config.py`):

   ```python
   pg_dsn=os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/sena")
   ```

2. **Setup Script** (`scripts/setup.sh`):

   ```bash
   DB_PASSWORD="${SENA_DB_PASSWORD:-postgres}"
   ```

3. **Environment File** (`.env`):

   ```bash
   export PG_DSN="postgresql://postgres:postgres@localhost:5432/sena"
   ```

### Using a Custom Password

**Option 1: Before running setup**

```bash
export SENA_DB_PASSWORD="my_secure_password"
./scripts/setup.sh
```

**Option 2: Edit .env after setup**

```bash
# In .env file:
export PG_DSN="postgresql://postgres:my_secure_password@localhost:5432/sena"
```

**Option 3: Set at runtime**

```bash
export PG_DSN="postgresql://postgres:my_secure_password@localhost:5432/sena"
.venv/bin/python ui_nicegui/sena.py
```

### Manual PostgreSQL Setup

If you prefer manual setup:

```bash
# Reset postgres password
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"

# Create database
sudo -u postgres psql -c "CREATE DATABASE sena;"

# Enable pgvector (optional, for vector search)
sudo -u postgres psql -d sena -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Grant privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE sena TO postgres;"
```

---

## Environment Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PG_DSN` | `postgresql://postgres:postgres@localhost:5432/sena` | PostgreSQL connection string |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `OLLAMA_CHAT_MODEL` | `qwen2.5:7b-instruct` | LLM for chat responses |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Model for embeddings |

### RAG Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_DEBUG` | `0` | Enable debug logging |
| `CHAT_MAX_TOKENS` | `1024` | Max tokens for responses |
| `LIVE_SUMMARY_ENABLED` | `true` | Enable live output summaries |
| `LIVE_OUTPUT_MODE` | `summary` | Output mode: `summary` or `full` |

### SSH Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SENA_SSH_CONFIG` | `configs/ssh.json` | Path to SSH config file |
| `METRICS_ENABLED` | `true` | Enable graph metrics logging |
| `METRICS_PATH` | `logs/graph_metrics.jsonl` | Metrics log path |

### Example .env File

```bash
# PostgreSQL Database
export PG_DSN="postgresql://postgres:postgres@localhost:5432/sena"

# Ollama LLM Settings
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_CHAT_MODEL="qwen2.5:7b-instruct"
export OLLAMA_CHAT_SMALL_MODEL="nemotron-mini:4b"
export OLLAMA_EMBED_MODEL="nomic-embed-text"

# RAG Settings
export RAG_DEBUG="0"
export LIVE_SUMMARY_ENABLED="true"
export LIVE_OUTPUT_MODE="summary"
export CHAT_MAX_TOKENS="1024"

# Metrics
export METRICS_ENABLED="true"
export METRICS_PATH="logs/graph_metrics.jsonl"

# SSH Config
export SENA_SSH_CONFIG="configs/ssh.json"
```

---

## Setup Script Reference

The setup script (`scripts/setup.sh`) automates the entire setup process.

### Usage

```bash
./scripts/setup.sh [command] [options]
```

### Setup Commands

| Command | Description |
|---------|-------------|
| `./scripts/setup.sh` | Full setup (all steps) |
| `./scripts/setup.sh postgres` | Only PostgreSQL setup |
| `./scripts/setup.sh python` | Only Python virtual environment |
| `./scripts/setup.sh deps` | Only install dependencies |
| `./scripts/setup.sh env` | Only create .env file |

### Data Commands

| Command | Description |
|---------|-------------|
| `./scripts/setup.sh prepare` | Convert raw data files to JSONL |
| `./scripts/setup.sh index` | Index JSONL into PostgreSQL |
| `./scripts/setup.sh update` | Full data refresh (prepare + index) |
| `./scripts/setup.sh verify-db` | Check database contents |

### Verification

| Command | Description |
|---------|-------------|
| `./scripts/setup.sh verify` | Verify complete setup |

### Examples

```bash
# Full setup on a new system
./scripts/setup.sh

# Only fix PostgreSQL connection
./scripts/setup.sh postgres

# Refresh all data in database
./scripts/setup.sh update

# Check what's in the database
./scripts/setup.sh verify-db
```

---

## Start the Agent

### 1) Start Ollama + pull models (local LLM)

```bash
ollama serve
ollama pull qwen2.5:7b-instruct
ollama pull nemotron-mini:4b
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text
```

### 2) Start the UI agent

```bash
source .env
.venv/bin/python ui_nicegui/sena.py
```

The UI will print a local URL (default port 8082).

### 3) Optional: run the graph directly (CLI)

```bash
.venv/bin/python - <<'PY'
from src.graph.graph import run_graph
result = run_graph("Show hosts in rack B19")
print(result.response)
PY
```

---

## Sample Prompts

### RAG (testcase + metadata)
- Show hosts in rack B19
- Show system with service tag D86HXK2
- List test case TC-15174
- Show detailed steps for TC-15174

### Live RAG (SSH)
- Get `dmesg | tail -n 200` from aseda-VMware-Vm1
- Run `lscpu` on aseda-VMware-Vm1
- /live nvme aseda-VMware-Vm1
- /live dmesg aseda-VMware-Vm1

### Orchestrator (testcase + audit)
- Run testcase TC-3362 on host 98HLZ85
- Run testcase TC-3362 on host 98HLZ85 in background
- /test status TC-3362 98HLZ85
- /test log TC-3362 98HLZ85
- /audit testcase TC-15174 log path /home/aseda/project/sena_try/data/exports/run_TC-15174_98HLZ85_20260120T201713Z

### Multi-agent commands
- /summary live
- /summary context
- /debug last output
- /memory
- /safety
- /health aseda-VMware-Vm1
- /inventory rack D1
- /regression TC-3362 host 98HLZ85
- /metrics
- /ingest /path/to/file.csv
- /policy
- /feedback
- /recovery

---

## Data Indexing

### Directory Structure

```
data/
├── raw/                    # Original source files
│   ├── test_cases/         # Test case CSV/Excel files
│   └── system_logs/        # System inventory files
└── processed/              # JSONL files (generated)
    ├── test_cases.jsonl
    └── system_logs.jsonl
```

### Indexing Workflow

1. **Place raw data files** in `data/raw/test_cases/` and `data/raw/system_logs/`

2. **Run data update**:

   ```bash
   ./scripts/setup.sh update
   ```

3. **Or run steps separately**:

   ```bash
   # Step 1: Convert raw files to JSONL
   ./scripts/setup.sh prepare
   
   # Step 2: Index into PostgreSQL with embeddings
   ./scripts/setup.sh index
   ```

### Manual Indexing

```bash
source .env

# Prepare data
.venv/bin/python -m src.ingest.prepare_data

# Index with embeddings
.venv/bin/python index_data.py --processed-dir data/processed --progress-every 50
```

### Verify Database Contents

```bash
./scripts/setup.sh verify-db
```

Expected output:

```
==================================================
Database Contents:
==================================================
  Test Cases:      150 records (150 with embeddings)
  System Logs:      45 records (45 with embeddings)
==================================================

[OK] Database has data!
```

---

## Troubleshooting

### PostgreSQL Connection Failed

**Error**: `password authentication failed for user "postgres"`

**Solution**:

```bash
# Reset the password
./scripts/setup.sh postgres

# Or manually:
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
```

### Database Does Not Exist

**Error**: `database "sena" does not exist`

**Solution**:

```bash
sudo -u postgres psql -c "CREATE DATABASE sena;"
```

### Ollama Not Running

**Error**: `connection refused` on embedding generation

**Solution**:

```bash
# Start Ollama
ollama serve

# In another terminal, pull the embedding model
ollama pull nomic-embed-text
```

### Missing pgvector Extension

**Error**: `extension "vector" does not exist`

**Solution**:

```bash
# Install pgvector (Ubuntu/Debian)
sudo apt install postgresql-16-pgvector

# Enable in database
sudo -u postgres psql -d sena -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Permission Denied on Files

**Error**: `PermissionError: [Errno 13] Permission denied`

**Solution**:

```bash
# Fix file ownership
sudo chown -R $(whoami):$(whoami) .

# Fix specific files
sudo chown $(whoami):$(whoami) chat_history_lite.jsonl session_live.json
```

### Virtual Environment Not Found

**Error**: `ModuleNotFoundError`

**Solution**:

```bash
# Recreate virtual environment
./scripts/setup.sh python
./scripts/setup.sh deps
```

---

## Running the Application

After setup is complete:

```bash
# 1. Source environment
source .env

# 2. Ensure Ollama is running
ollama serve &

# 3. Start the application
.venv/bin/python ui_nicegui/sena.py
```

The UI will be available at:

- <http://localhost:8082>

---

## Support

For issues, check:

1. This guide's [Troubleshooting](#troubleshooting) section
2. Run `./scripts/setup.sh verify` to diagnose problems
3. Check logs with `RAG_DEBUG=1` enabled
