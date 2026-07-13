"""Classify nodes by path and name heuristics."""

from __future__ import annotations

import fnmatch
from pathlib import Path

import yaml

from project_graph.config import TOOL_CONFIG_DIR
from project_graph.models import Node, NodeType


class NodeClassifier:
    """Apply YAML rules to classify graph nodes."""

    def __init__(self, rules_path: Path | None = None) -> None:
        path = rules_path or TOOL_CONFIG_DIR / "node_rules.yaml"
        self.rules = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}

    def classify(self, node: Node) -> NodeType:
        """Return best NodeType for a node."""
        if node.type not in (NodeType.UNKNOWN, NodeType.FUNCTION, NodeType.METHOD):
            return node.type
        source = node.source_file or ""
        qname = node.qualified_name
        for rule in self.rules.get("path_rules", []):
            if fnmatch.fnmatch(source, rule["pattern"]):
                return NodeType(rule["type"])
        for rule in self.rules.get("name_rules", []):
            suffix = rule.get("suffix", "")
            if qname.endswith(suffix) or node.name.endswith(suffix):
                return NodeType(rule["type"])
        return node.type

    def reclassify_graph(self, nodes: list[Node]) -> list[Node]:
        """Reclassify all nodes in place."""
        result: list[Node] = []
        for node in nodes:
            new_type = self.classify(node)
            if new_type != node.type:
                node = node.model_copy(update={"type": new_type})
            result.append(node)
        return result
