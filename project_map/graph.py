"""Execution graph with node removal for incremental traces."""

from __future__ import annotations

from project_map.models.graph import ExecutionGraph


class MapGraph(ExecutionGraph):
    """ExecutionGraph that can drop nodes from a changed file."""

    def remove_nodes(self, node_ids: set[str]) -> None:
        """Remove nodes and any edges that touch them."""
        for node_id in node_ids:
            self._nodes.pop(node_id, None)
            if self._graph.has_node(node_id):
                self._graph.remove_node(node_id)
        self._edges = [
            edge
            for edge in self._edges
            if edge.from_node not in node_ids and edge.to_node not in node_ids
        ]

    def edges_from(self, node_id: str) -> list:
        """Return outgoing edges."""
        return [edge for edge in self._edges if edge.from_node == node_id]
