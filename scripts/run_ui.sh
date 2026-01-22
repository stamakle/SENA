#!/usr/bin/env bash
set -euo pipefail

# Conversational defaults for the UI
export RAG_MODE="${RAG_MODE:-general}"
export RAG_ONLY="${RAG_ONLY:-false}"
export SUMMARY_ENABLED="${SUMMARY_ENABLED:-true}"
export SUMMARY_MIN_MESSAGES="${SUMMARY_MIN_MESSAGES:-4}"
export SUMMARY_UPDATE_EVERY="${SUMMARY_UPDATE_EVERY:-3}"
export CHAT_MAX_TOKENS="${CHAT_MAX_TOKENS:-1400}"
export REQUEST_TIMEOUT_SEC="${REQUEST_TIMEOUT_SEC:-120}"

# Live RAG defaults
export RAG_DEBUG="${RAG_DEBUG:-1}"
export LIVE_OUTPUT_MODE="${LIVE_OUTPUT_MODE:-full}"
export LIVE_SUMMARY_ENABLED="${LIVE_SUMMARY_ENABLED:-true}"
export LIVE_STRICT_MODE="${LIVE_STRICT_MODE:-false}"
export LIVE_AUTO_EXECUTE="${LIVE_AUTO_EXECUTE:-true}"
export LIVE_RACK_FAILURE_TTL_SEC="${LIVE_RACK_FAILURE_TTL_SEC:-600}"
export LIVE_RACK_TIMEOUT_SEC="${LIVE_RACK_TIMEOUT_SEC:-8}"
export LIVE_RACK_MAX_WORKERS="${LIVE_RACK_MAX_WORKERS:-4}"

echo "Starting UI with conversational defaults:"
echo "  RAG_MODE=$RAG_MODE"
echo "  RAG_ONLY=$RAG_ONLY"
echo "  SUMMARY_ENABLED=$SUMMARY_ENABLED"
echo "  SUMMARY_MIN_MESSAGES=$SUMMARY_MIN_MESSAGES"
echo "  SUMMARY_UPDATE_EVERY=$SUMMARY_UPDATE_EVERY"
echo "  CHAT_MAX_TOKENS=$CHAT_MAX_TOKENS"
echo "  REQUEST_TIMEOUT_SEC=$REQUEST_TIMEOUT_SEC"
echo "  RAG_DEBUG=$RAG_DEBUG"
echo "  LIVE_OUTPUT_MODE=$LIVE_OUTPUT_MODE"
echo "  LIVE_SUMMARY_ENABLED=$LIVE_SUMMARY_ENABLED"
echo "  LIVE_STRICT_MODE=$LIVE_STRICT_MODE"
echo "  LIVE_AUTO_EXECUTE=$LIVE_AUTO_EXECUTE"
echo "  LIVE_RACK_FAILURE_TTL_SEC=$LIVE_RACK_FAILURE_TTL_SEC"
echo "  LIVE_RACK_TIMEOUT_SEC=$LIVE_RACK_TIMEOUT_SEC"
echo "  LIVE_RACK_MAX_WORKERS=$LIVE_RACK_MAX_WORKERS"

# Resolve absolute path to project root using BASH_SOURCE BEFORE changing directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJ_DIR="$(dirname "$SCRIPT_DIR")"
echo "Project Root: $PROJ_DIR"

# Create a temporary working directory to avoid permission issues with .nicegui folder
# occurring if previously run as root
WORKDIR="/tmp/sena_ui_workdir_$(date +%s)"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

if [ -f "$PROJ_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJ_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

echo "Running SENA from $WORKDIR using $PYTHON"
exec "$PYTHON" "$PROJ_DIR/ui_nicegui/sena.py"
