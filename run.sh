#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then uv sync; fi
uv run python -m project_graph "$@"
