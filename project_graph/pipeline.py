"""Build pipeline orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from project_graph.builder.infra_detector import InfraDetector
from project_graph.builder.node_classifier import NodeClassifier
from project_graph.builder.scenario_tracer import ScenarioTracer
from project_graph.config import get_output_dir
from project_graph.export.json_exporter import export_graph, load_graph
from project_graph.models import ExecutionGraph
from project_graph.parsing.ast_store import ASTStore
from project_graph.resolution.incremental_call_graph import IncrementalCallGraphBuilder
from project_graph.resolution.jedi_resolver import clear_jedi_cache
from project_graph.trace_roots.merger import merge_trace_subgraph
from project_graph.trace_roots.models import TraceDoneEntry, TraceRoot
from project_graph.trace_roots.resolver import RootResolver, RootResolveError
from project_graph.trace_roots.store import TraceStore


@dataclass
class TraceResult:
    call_graph: ExecutionGraph
    execution_graph: ExecutionGraph
    processed_roots: list[str]
    stats: dict = field(default_factory=dict)


def trace_roots(
    roots: list[TraceRoot],
    *,
    reset_call_graph: bool = False,
    clear_jedi_cache_flag: bool = False,
    output_dir: Path | None = None,
    from_queue: bool = False,
) -> TraceResult:
    """Trace explicit roots and merge into execution_graph.json."""
    out = output_dir or get_output_dir()
    execution_graph_path = out / "execution_graph.json"
    call_graph_path = out / "call_graph.json"

    if clear_jedi_cache_flag:
        clear_jedi_cache()

    if reset_call_graph and call_graph_path.exists():
        call_graph_path.unlink()

    incremental = IncrementalCallGraphBuilder.load_or_empty(call_graph_path)
    ast_store = ASTStore()
    resolver = RootResolver(incremental.graph, ast_store=ast_store)
    tracer = ScenarioTracer()
    classifier = NodeClassifier()
    store = TraceStore()

    if execution_graph_path.exists():
        execution_graph = load_graph(execution_graph_path)
    else:
        execution_graph = ExecutionGraph()

    processed_ids: list[str] = []
    errors: list[str] = []

    for root in roots:
        root_id = TraceStore.ensure_id(root)
        try:
            resolved = resolver.resolve(root)
            incremental.expand_from(resolved)
            resolver = RootResolver(incremental.graph, ast_store=ast_store)

            for node in classifier.reclassify_graph(incremental.graph.nodes):
                incremental.graph.add_node(node)

            subgraph = tracer.trace_from_roots([resolved], incremental.graph)
            subgraph = InfraDetector().enrich(subgraph)
            for node in classifier.reclassify_graph(subgraph.nodes):
                subgraph.add_node(node)
            execution_graph = merge_trace_subgraph(
                execution_graph,
                subgraph,
                root_id=root_id,
                entry_node_id=resolved.entry_node.id,
            )
            store.upsert_done(
                TraceDoneEntry(
                    id=root_id,
                    pointer=root.pointer,
                    processed_at=datetime.now().isoformat(timespec="seconds"),
                    node_count=subgraph.stats()["node_count"],
                    edge_count=subgraph.stats()["edge_count"],
                )
            )
            processed_ids.append(root_id)
            print(f"Traced root '{root_id}': {subgraph.stats()['node_count']} nodes")
        except (RootResolveError, RuntimeError) as exc:
            errors.append(f"{root_id}: {exc}")
            print(f"Failed root '{root_id}': {exc}")

    export_graph(
        incremental.graph,
        call_graph_path,
        {"stage": "call_graph", "unresolved_ratio": incremental.unresolved_ratio()},
    )
    export_graph(
        execution_graph,
        execution_graph_path,
        {"stage": "execution_graph", "processed_roots": processed_ids},
    )

    if from_queue and processed_ids:
        store.remove_from_queue(set(processed_ids))

    stats = {
        "call_graph": incremental.graph.stats(),
        "execution_graph": execution_graph.stats(),
        "processed_roots": processed_ids,
        "errors": errors,
    }
    if errors:
        print(f"Completed with {len(errors)} error(s).")
    return TraceResult(incremental.graph, execution_graph, processed_ids, stats)
