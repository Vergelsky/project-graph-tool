"""Merge trace subgraphs into one execution graph."""

from __future__ import annotations

from project_graph.models import ExecutionGraph, NodeType


def merge_trace_subgraph(
    base_graph: ExecutionGraph,
    subgraph: ExecutionGraph,
    root_id: str,
    entry_node_id: str,
) -> ExecutionGraph:
    """Replace prior subgraph for root_id and merge new subgraph."""
    stripped = strip_root_subgraph(base_graph, root_id, entry_node_id)
    for node in subgraph.nodes:
        stripped.add_node(node)
    for edge in subgraph.edges:
        stripped.add_edge(edge)
    return stripped


def strip_root_subgraph(
    graph: ExecutionGraph,
    root_id: str,
    entry_node_id: str,
) -> ExecutionGraph:
    """Remove nodes belonging to a previous trace of root_id."""
    entry_ids = {
        node.id
        for node in graph.nodes
        if node.type == NodeType.ENTRY_POINT and node.metadata.get("root_id") == root_id
    }
    entry_ids.add(entry_node_id)

    remove_ids: set[str] = set()
    for entry_id in entry_ids:
        remove_ids.add(entry_id)
        remove_ids.update(_nodes_reachable_by_scenario_entry(graph, entry_id))

    result = ExecutionGraph()
    for node in graph.nodes:
        if node.id not in remove_ids:
            result.add_node(node)
    for edge in graph.edges:
        if edge.from_node not in remove_ids and edge.to_node not in remove_ids:
            result.add_edge(edge)
    return result


def _nodes_reachable_by_scenario_entry(graph: ExecutionGraph, entry_id: str) -> set[str]:
    """Collect nodes tagged with scenario_entry matching entry_id."""
    tagged: set[str] = set()
    for edge in graph.edges:
        if edge.metadata.get("scenario_entry") == entry_id:
            tagged.add(edge.from_node)
            tagged.add(edge.to_node)
    changed = True
    while changed:
        changed = False
        for edge in graph.edges:
            scenario_entry = edge.metadata.get("scenario_entry")
            if scenario_entry != entry_id:
                continue
            for node_id in (edge.from_node, edge.to_node):
                if node_id not in tagged:
                    tagged.add(node_id)
                    changed = True
    return tagged
