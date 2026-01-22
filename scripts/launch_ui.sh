#!/bin/bash
# Launch the Sena Premium UI

cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONPATH=$PYTHONPATH:.

# Fix for permission errors on .nicegui folder
export NICEGUI_STORAGE_PATH=/tmp/sena_nicegui_storage
mkdir -p $NICEGUI_STORAGE_PATH

echo "Starting Sena UI on http://localhost:8085..."
echo "Bootstrapping search index (if needed)..."
python3 scripts/bootstrap_search.py || true
python3 ui_nicegui/sena.py
