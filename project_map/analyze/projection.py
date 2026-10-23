"""Project the function graph to file or package cards. The tracer never calls this."""

from __future__ import annotations

from project_map.ids import make_node_id
from project_map.models import Edge, Node, NodeType

from project_map.graph import MapGraph


def project(graph: MapGraph, level: str) -> MapGraph:
    """Return the graph at function, file, or package granularity."""
    if level == "function":
        return graph
    if level not in ("file", "package"):
        raise ValueError(f"Unknown display level: {level}")

    groups: dict[str, list[Node]] = {}
    member_group: dict[str, str] = {}
    for node in graph.nodes:
        group_id = _group_id(node, level)
        groups.setdefault(group_id, []).append(node)
        member_group[node.id] = group_id

    projected = MapGraph()
    node_type = NodeType.FILE if level == "file" else NodeType.PACKAGE
    for group_id, members in groups.items():
        title = _group_label(members, level, group_id)
        projected.add_node(
            Node(
                id=group_id,
                type=node_type,
                name=title,
                qualified_name=title,
                source_file=members[0].source_file if level == "file" else None,
                metadata={
                    "level": level,
                    "members": [member.id for member in members],
                    "member_names": [member.qualified_name for member in members],
                },
            )
        )

    seen: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        origin = member_group.get(edge.from_node)
        dest = member_group.get(edge.to_node)
        if not origin or not dest or origin == dest:
            continue
        key = (origin, dest, edge.type.value)
        if key in seen:
            continue
        seen.add(key)
        projected.add_edge(Edge(from_node=origin, to_node=dest, type=edge.type))
    return projected


def _group_id(node: Node, level: str) -> str:
    """Stable id for the card that contains this function."""
    if not node.source_file:
        return make_node_id(f"external:{node.id}")
    path = node.source_file.replace("\\", "/")
    if level == "file":
        return make_node_id(f"file:{path}")
    parent = path.rsplit("/", 1)[0] if "/" in path else "."
    return make_node_id(f"package:{parent}")


def _group_label(members: list[Node], level: str, group_id: str) -> str:
    """Short name shown on the collapsed card."""
    source = next((member.source_file for member in members if member.source_file), "") or ""
    source = source.replace("\\", "/")
    if level == "file":
        return source or group_id
    if "/" not in source:
        return "."
    return source.rsplit("/", 1)[0]
