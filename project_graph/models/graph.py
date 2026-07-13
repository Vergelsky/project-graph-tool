"""Execution graph wrapper over NetworkX."""

from __future__ import annotations

from typing import Any

import networkx as nx

from project_graph.models.edge import Edge, EdgeType
from project_graph.models.node import Node


class ExecutionGraph:
    """Directed graph of project execution flow."""

    def __init__(self) -> None:
        self._graph = nx.DiGraph()
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    def add_node(self, node: Node) -> None:
        """Add or update a node."""
        self._nodes[node.id] = node
        self._graph.add_node(node.id, **node.model_dump(mode="json"))

    def get_node(self, node_id: str) -> Node | None:
        """Return node by id."""
        return self._nodes.get(node_id)

    def add_edge(self, edge: Edge) -> None:
        """Add a directed edge."""
        self._edges.append(edge)
        self._graph.add_edge(
            edge.from_node,
            edge.to_node,
            type=edge.type.value,
            metadata=edge.metadata,
        )

    @property
    def nodes(self) -> list[Node]:
        """Return all nodes."""
        return list(self._nodes.values())

    @property
    def edges(self) -> list[Edge]:
        """Return all edges."""
        return list(self._edges)

    @property
    def nx(self) -> nx.DiGraph:
        """Return underlying NetworkX graph."""
        return self._graph

    def get_path(self, from_id: str, to_id: str, cutoff: int = 20) -> list[list[str]]:
        """Find simple paths between two nodes."""
        if from_id not in self._graph or to_id not in self._graph:
            return []
        try:
            return list(nx.all_simple_paths(self._graph, from_id, to_id, cutoff=cutoff))
        except nx.NetworkXNoPath:
            return []

    def get_subgraph(self, root_id: str, max_depth: int = 15) -> ExecutionGraph:
        """Build subgraph reachable from root within max_depth."""
        if root_id not in self._graph:
            return ExecutionGraph()
        reachable: set[str] = {root_id}
        frontier = {root_id}
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                for _, target in self._graph.out_edges(node_id):
                    if target not in reachable:
                        reachable.add(target)
                        next_frontier.add(target)
            if not next_frontier:
                break
            frontier = next_frontier
        sub = ExecutionGraph()
        for node_id in reachable:
            if node_id in self._nodes:
                sub.add_node(self._nodes[node_id])
        for edge in self._edges:
            if edge.from_node in reachable and edge.to_node in reachable:
                sub.add_edge(edge)
        return sub

    def stats(self) -> dict[str, Any]:
        """Return graph statistics."""
        type_counts: dict[str, int] = {}
        for node in self._nodes.values():
            type_counts[node.type.value] = type_counts.get(node.type.value, 0) + 1
        edge_type_counts: dict[str, int] = {}
        for edge in self._edges:
            edge_type_counts[edge.type.value] = edge_type_counts.get(edge.type.value, 0) + 1
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "node_types": type_counts,
            "edge_types": edge_type_counts,
        }

    def to_export_dict(self) -> dict[str, Any]:
        """Export graph as JSON-serializable dict."""
        return {
            "nodes": [n.to_export_dict() for n in self._nodes.values()],
            "edges": [e.to_export_dict() for e in self._edges],
        }

    @classmethod
    def from_export_dict(cls, data: dict[str, Any]) -> ExecutionGraph:
        """Load graph from exported JSON."""
        graph = cls()
        for raw in data.get("nodes", []):
            graph.add_node(Node.model_validate(raw))
        for raw in data.get("edges", []):
            graph.add_edge(Edge.model_validate(raw))
        return graph
