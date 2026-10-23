"""Job folder: source, entries, graph, descriptions, and the call cache."""

from __future__ import annotations

import json
from pathlib import Path

from project_map.ids import make_node_id
from project_map.models import Edge, EdgeType, Node, NodeType

from project_map.analyze.files import file_hashes
from project_map.analyze.trace import ExecutionTracer, ExpandedKey, locate_entry
from project_map.graph import MapGraph
from project_map.libraries.base import LibraryBridge, ProjectTarget
from project_map.source import ensure_checkout


def create_job(job_dir: Path, source: str, entries: list[str], *, job_id: str | None = None) -> Path:
    """Create job.json. Local directories are stored as absolute paths."""
    if (job_dir / "job.json").exists():
        raise FileExistsError(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": job_id or job_dir.name,
        "source": _source_spec(source),
        "entries": [parse_entry(value) for value in entries],
        "token_env": "PROJECT_MAP_GIT_TOKEN",
    }
    _write_json(job_dir / "job.json", payload)
    return job_dir


def set_entries(job_dir: Path, values: list[str]) -> list[dict]:
    """Replace the entry list. The cabinet keeps the one point the user picked."""
    job = load_job(job_dir)
    job["entries"] = [parse_entry(value) for value in values]
    _write_json(job_dir / "job.json", job)
    return job["entries"]


def update_source(job_dir: Path, source: str) -> dict:
    """Point the job at another repository address."""
    job = load_job(job_dir)
    job["source"] = _source_spec(source)
    _write_json(job_dir / "job.json", job)
    return job["source"]


def add_entry(job_dir: Path, value: str) -> dict:
    """Append an entry if this file:line or name is not already listed."""
    job = load_job(job_dir)
    entry = parse_entry(value)
    if not any(_same_entry(existing, entry) for existing in job["entries"]):
        job["entries"].append(entry)
        _write_json(job_dir / "job.json", job)
    return entry


def trace_job(
    job_dir: Path,
    *,
    bridges: list[LibraryBridge] | None = None,
    resolver=None,
    token: str | None = None,
) -> MapGraph:
    """Trace every entry into the job graph. Unchanged files are not resolved again."""
    job = load_job(job_dir)
    repo = ensure_checkout(job, job_dir, token=token)
    graph, hashes, expanded = load_cache(job_dir)
    current = file_hashes(repo)
    tracer = ExecutionTracer(
        repo,
        graph,
        bridges=bridges,
        resolver=resolver,
        file_hashes=hashes,
        expanded=expanded,
        current_hashes=current,
    )
    tracer.invalidate_changed_files()
    for entry in job["entries"]:
        target = locate_entry(repo, entry.get("file"), entry.get("line"), entry.get("qualified_name"))
        tracer.expand(target)
        _add_entry_node(tracer.graph, entry, target)
    save_graph(job_dir, tracer.graph)
    save_cache(job_dir, tracer.graph, tracer.file_hashes, tracer.expanded)
    return tracer.graph


def load_job(job_dir: Path) -> dict:
    """Read job.json."""
    path = job_dir / "job.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def load_graph(job_dir: Path) -> MapGraph:
    """Read execution_graph.json."""
    path = job_dir / "execution_graph.json"
    graph = MapGraph()
    if not path.exists():
        return graph
    data = json.loads(path.read_text(encoding="utf-8"))
    return _graph_from_dict(data)


def save_graph(job_dir: Path, graph: MapGraph) -> None:
    """Write the function-level graph. Descriptions are not stored here."""
    for node in graph.nodes:
        node.description = None
    _write_json(job_dir / "execution_graph.json", graph.to_export_dict())


def parse_entry(value: str) -> dict:
    """Parse file:line or a qualified name."""
    text = value.strip().replace("\\", "/")
    head, sep, tail = text.rpartition(":")
    if sep and tail.isdigit() and head:
        return {"id": text, "file": head, "line": int(tail)}
    return {"id": text, "qualified_name": text}


def _source_spec(source: str) -> dict:
    """Classify a path or URL."""
    if "://" in source:
        return {"kind": "git", "url": source}
    path = Path(source).expanduser().resolve()
    return {"kind": "local", "path": str(path)}


def _same_entry(left: dict, right: dict) -> bool:
    """True when two entry pointers name the same place."""
    if left.get("file") and right.get("file"):
        return left.get("file") == right.get("file") and left.get("line") == right.get("line")
    return left.get("qualified_name") == right.get("qualified_name") and bool(left.get("qualified_name"))


def _add_entry_node(graph: MapGraph, entry: dict, target: ProjectTarget) -> None:
    """Root card pointing at the resolved function."""
    root_id = make_node_id(f"ROOT:{entry.get('id') or target.qualified_name}")
    graph.add_node(
        Node(
            id=root_id,
            type=NodeType.ENTRY_POINT,
            name=str(entry.get("id") or target.qualified_name),
            qualified_name=target.qualified_name,
            source_file=target.source_file,
            line_start=target.line,
            metadata={"root_id": entry.get("id"), "resolved_qualified_name": target.qualified_name},
        )
    )
    func_id = make_node_id(target.qualified_name, target.source_file, target.line)
    for edge in graph.edges:
        if edge.from_node == root_id and edge.to_node == func_id and edge.type == EdgeType.CALLS:
            return
    graph.add_edge(
        Edge(
            from_node=root_id,
            to_node=func_id,
            type=EdgeType.CALLS,
            metadata={
                "follow": True,
                "qualified_name": target.qualified_name,
                "source_file": target.source_file,
                "line": target.line,
            },
        )
    )


def load_cache(job_dir: Path) -> tuple[MapGraph, dict[str, str], set[ExpandedKey]]:
    """Load the incremental call cache, or start empty."""
    path = job_dir / "cache" / "call_graph.json"
    if not path.exists():
        return MapGraph(), {}, set()
    data = json.loads(path.read_text(encoding="utf-8"))
    graph = _graph_from_dict(data.get("graph") or {})
    hashes = {str(key): str(value) for key, value in (data.get("file_hashes") or {}).items()}
    expanded = {
        (item[0], int(item[1]), item[2])
        for item in data.get("expanded") or []
        if isinstance(item, list) and len(item) == 3
    }
    return graph, hashes, expanded


def save_cache(job_dir: Path, graph: MapGraph, hashes: dict[str, str], expanded: set[ExpandedKey]) -> None:
    """Persist hashes and which functions were fully resolved."""
    payload = {
        "file_hashes": hashes,
        "expanded": [list(item) for item in sorted(expanded)],
        "graph": graph.to_export_dict(),
    }
    _write_json(job_dir / "cache" / "call_graph.json", payload)


def _graph_from_dict(data: dict) -> MapGraph:
    """Load nodes and edges into a MapGraph."""
    graph = MapGraph()
    for raw in data.get("nodes") or []:
        graph.add_node(Node.model_validate(raw))
    for raw in data.get("edges") or []:
        graph.add_edge(Edge.model_validate(raw))
    return graph


def _write_json(path: Path, payload: dict) -> None:
    """Write UTF-8 JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
