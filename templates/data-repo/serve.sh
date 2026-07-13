#!/usr/bin/env bash
set -euo pipefail
DATA_ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$DATA_ROOT/../project-graph-tool" && pwd)"
exec uv run --directory "$TOOL_ROOT" python serve.py --data-dir "$DATA_ROOT" --port "${1:-8765}"
