#!/usr/bin/env bash
set -euo pipefail
DATA_ROOT="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$DATA_ROOT/../project-graph-tool" && pwd)"
export PROJECT_GRAPH_DATA="$DATA_ROOT"
cd "$DATA_ROOT"
exec uv run --directory "$TOOL_ROOT" python -m project_graph "$@"
