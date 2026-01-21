#!/usr/bin/env bash
set -euo pipefail

PYTHONPYCACHEPREFIX=/tmp/pycache .venv/bin/python -m pytest -q tests/test_prompts.py
