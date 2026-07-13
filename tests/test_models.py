"""Tests for graph models."""

from project_graph.models import Edge, EdgeType, ExecutionGraph, Node, NodeType


def test_node_serialization_roundtrip() -> None:
    """Serialize and deserialize a node."""
    node = Node(
        id="test.node",
        type=NodeType.VIEW,
        name="TestView",
        qualified_name="app.views.TestView",
        source_file="app/views.py",
        line_start=10,
        line_end=20,
        metadata={"url": "/test/"},
    )
    data = node.to_export_dict()
    restored = Node.model_validate(data)
    assert restored.id == node.id
    assert restored.type == NodeType.VIEW


def test_edge_alias_fields() -> None:
    """Load edge with from/to aliases."""
    edge = Edge.model_validate({"from": "a", "to": "b", "type": "CALLS"})
    assert edge.from_node == "a"
    assert edge.to_node == "b"
    assert edge.to_export_dict()["from"] == "a"


def test_execution_graph_path() -> None:
    """Find path between connected nodes."""
    graph = ExecutionGraph()
    graph.add_node(Node(id="a", type=NodeType.ENTRY_POINT, name="a", qualified_name="a"))
    graph.add_node(Node(id="b", type=NodeType.VIEW, name="b", qualified_name="b"))
    graph.add_edge(Edge(from_node="a", to_node="b", type=EdgeType.CALLS))
    paths = graph.get_path("a", "b")
    assert paths == [["a", "b"]]


def test_execution_graph_export_roundtrip() -> None:
    """Export and import graph."""
    graph = ExecutionGraph()
    graph.add_node(Node(id="n1", type=NodeType.SERVICE, name="Svc", qualified_name="svc"))
    exported = graph.to_export_dict()
    loaded = ExecutionGraph.from_export_dict(exported)
    assert len(loaded.nodes) == 1
