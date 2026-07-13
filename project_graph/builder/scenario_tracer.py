"""Trace execution scenarios from explicit trace roots."""

from __future__ import annotations

from project_graph.config import MAX_TRACE_DEPTH
from project_graph.models import Edge, EdgeType, ExecutionGraph, Node, NodeType
from project_graph.trace_roots.resolver import ResolvedRoot


class ScenarioTracer:
    """BFS trace from trace roots through CALLS edges."""

    def __init__(self, max_depth: int = MAX_TRACE_DEPTH) -> None:
        self.max_depth = max_depth

    def trace_from_roots(
        self,
        resolved_roots: list[ResolvedRoot],
        call_graph: ExecutionGraph,
    ) -> ExecutionGraph:
        """Trace subgraphs from resolved trace roots."""
        entry_graph = ExecutionGraph()
        for resolved in resolved_roots:
            entry_graph.add_node(resolved.entry_node)
        return self.trace_from_entry_points(entry_graph, call_graph)

    def trace_from_entry_points(
        self,
        entry_graph: ExecutionGraph,
        call_graph: ExecutionGraph,
    ) -> ExecutionGraph:
        """Merge entry points with reachable call graph nodes."""
        merged = ExecutionGraph()
        for node in entry_graph.nodes:
            merged.add_node(node)
        for edge in entry_graph.edges:
            merged.add_edge(edge)

        qname_to_id = {n.qualified_name: n.id for n in call_graph.nodes}
        entry_ids = [n.id for n in entry_graph.nodes if n.type == NodeType.ENTRY_POINT]
        call_nx = call_graph.nx

        for ep_id in entry_ids:
            ep_node = entry_graph.get_node(ep_id)
            if not ep_node:
                continue
            start_id = ep_id
            method_qname = ep_node.metadata.get("resolved_qualified_name", ep_node.qualified_name)
            call_graph_node_id = ep_node.metadata.get("call_graph_node_id")
            if call_graph_node_id and call_graph.get_node(call_graph_node_id):
                start_id = call_graph_node_id
            elif method_qname in qname_to_id:
                start_id = qname_to_id[method_qname]
            if start_id != ep_id:
                merged.add_edge(
                    Edge(from_node=ep_id, to_node=start_id, type=EdgeType.CALLS, metadata={"traced": True})
                )

            reachable = self._bfs(call_nx, start_id, self.max_depth)
            if start_id not in reachable and start_id in call_nx:
                reachable.add(start_id)
            for node_id in reachable:
                node = call_graph.get_node(node_id)
                if node:
                    merged.add_node(node)
            for from_id in reachable:
                for _, to_id, data in call_nx.out_edges(from_id, data=True):
                    if to_id in reachable:
                        edge_type_str = data.get("type", EdgeType.CALLS.value)
                        try:
                            edge_type = EdgeType(edge_type_str)
                        except ValueError:
                            edge_type = EdgeType.CALLS
                        meta = data.get("metadata", {})
                        if not isinstance(meta, dict):
                            meta = {}
                        merged.add_edge(
                            Edge(
                                from_node=from_id,
                                to_node=to_id,
                                type=edge_type,
                                metadata={**meta, "scenario_entry": ep_id},
                            )
                        )
        return merged

    def _bfs(self, graph, start: str, max_depth: int) -> set[str]:
        """BFS reachable nodes."""
        if start not in graph:
            return set()
        visited: set[str] = {start}
        frontier = {start}
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                for _, target in graph.out_edges(node_id):
                    if target not in visited:
                        visited.add(target)
                        next_frontier.add(target)
            if not next_frontier:
                break
            frontier = next_frontier
        return visited
