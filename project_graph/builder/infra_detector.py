"""Detect infrastructure nodes (DB, cache, queue, external APIs)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

from project_graph.config import TOOL_CONFIG_DIR
from project_graph.models import Edge, EdgeType, ExecutionGraph, Node, NodeType
from project_graph.utils import make_node_id


class InfraDetector:
    """Add infrastructure nodes and edges based on config."""

    def __init__(self, config_path: Path | None = None) -> None:
        path = config_path or TOOL_CONFIG_DIR / "external_apis.yaml"
        self.config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}

    def enrich(self, graph: ExecutionGraph) -> ExecutionGraph:
        """Add DATABASE, CACHE, QUEUE, EXTERNAL_API nodes."""
        self._ensure_database_nodes(graph)
        self._tag_external_api_calls(graph)
        self._tag_queue_calls(graph)
        self._tag_cache_calls(graph)
        return graph

    def _ensure_database_nodes(self, graph: ExecutionGraph) -> None:
        """Add PostgreSQL and TABLE nodes for ORM models."""
        db_id = make_node_id("infra:PostgreSQL")
        if not graph.get_node(db_id):
            graph.add_node(
                Node(
                    id=db_id,
                    type=NodeType.DATABASE,
                    name="PostgreSQL",
                    qualified_name="PostgreSQL",
                    metadata={"engine": "postgresql"},
                )
            )
        for node in list(graph.nodes):
            if node.type != NodeType.ORM:
                continue
            table_name = node.metadata.get("db_table") or node.name.lower()
            table_id = make_node_id(f"table:{table_name}")
            if not graph.get_node(table_id):
                graph.add_node(
                    Node(
                        id=table_id,
                        type=NodeType.TABLE,
                        name=table_name,
                        qualified_name=f"table.{table_name}",
                        metadata={"model": node.qualified_name},
                    )
                )
            graph.add_edge(Edge(from_node=node.id, to_node=table_id, type=EdgeType.WRITES))
            graph.add_edge(Edge(from_node=table_id, to_node=db_id, type=EdgeType.READS))

    def _tag_external_api_calls(self, graph: ExecutionGraph) -> None:
        """Link calls to external API nodes."""
        for api in self.config.get("external_apis", []):
            pattern = api["qualified_name_pattern"]
            label = api["label"]
            api_id = make_node_id(f"external:{label}")
            if not graph.get_node(api_id):
                graph.add_node(
                    Node(
                        id=api_id,
                        type=NodeType.EXTERNAL_API,
                        name=label,
                        qualified_name=label,
                        metadata={"pattern": pattern},
                    )
                )
            for node in graph.nodes:
                if fnmatch.fnmatch(node.qualified_name, f"*{pattern}*") or fnmatch.fnmatch(
                    node.name, f"*{pattern}*"
                ):
                    graph.add_edge(Edge(from_node=node.id, to_node=api_id, type=EdgeType.CALLS))

    def _tag_queue_calls(self, graph: ExecutionGraph) -> None:
        """Add QUEUE nodes for Celery calls."""
        queue_id = make_node_id("infra:Celery")
        if not graph.get_node(queue_id):
            graph.add_node(
                Node(
                    id=queue_id,
                    type=NodeType.QUEUE,
                    name="Celery",
                    qualified_name="Celery",
                )
            )
        for edge in list(graph.edges):
            callee = edge.metadata.get("callee_text", "")
            if "apply_async" in callee or ".delay(" in callee:
                graph.add_edge(
                    Edge(from_node=edge.from_node, to_node=queue_id, type=EdgeType.EMITS, metadata=edge.metadata)
                )

    def _tag_cache_calls(self, graph: ExecutionGraph) -> None:
        """Add CACHE nodes for cache usage."""
        cache_id = make_node_id("infra:Redis")
        if not graph.get_node(cache_id):
            graph.add_node(
                Node(
                    id=cache_id,
                    type=NodeType.CACHE,
                    name="Redis",
                    qualified_name="Redis",
                )
            )
        for node in graph.nodes:
            if "cache" in node.qualified_name.lower():
                graph.add_edge(Edge(from_node=node.id, to_node=cache_id, type=EdgeType.USES))
