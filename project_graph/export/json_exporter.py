"""Export graph to JSON."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from project_graph.models.graph import ExecutionGraph


def export_graph(graph: ExecutionGraph, output_path: Path, meta: dict[str, Any] | None = None) -> None:
    """Write graph to JSON file."""
    payload = graph.to_export_dict()
    payload["meta"] = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        **(meta or {}),
        **graph.stats(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_graph(path: Path) -> ExecutionGraph:
    """Load graph from JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExecutionGraph.from_export_dict(data)
