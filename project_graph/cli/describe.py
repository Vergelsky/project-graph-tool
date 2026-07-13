"""Describe-node command for manual AI descriptions."""

from pathlib import Path

from project_graph.config import get_output_dir, get_repo_root
from project_graph.export.json_exporter import load_graph


def cmd_describe_node(args) -> int:
    """Print node metadata and source code snippet."""
    output_dir = get_output_dir()
    graph_path = Path(args.output)
    if not graph_path.is_absolute():
        graph_path = output_dir.parent / graph_path
    if not graph_path.exists():
        print(f"Graph not found: {graph_path}. Run build first.")
        return 1
    graph = load_graph(graph_path)

    matches = [n for n in graph.nodes if args.node_id in n.id or args.node_id in n.qualified_name]
    if not matches:
        print(f"No node matching: {args.node_id}")
        return 1

    node = matches[0]
    repo_root = get_repo_root()
    print("=== Node ===")
    print(f"id: {node.id}")
    print(f"type: {node.type.value}")
    print(f"name: {node.name}")
    print(f"qualified_name: {node.qualified_name}")
    print(f"source: {node.source_file}:{node.line_start}-{node.line_end}")
    print(f"metadata: {node.metadata}")
    print()

    if node.source_file and node.line_start:
        full_path = repo_root / node.source_file
        if full_path.exists():
            lines = full_path.read_text(encoding="utf-8").splitlines()
            start = max(0, node.line_start - 1)
            end = min(len(lines), node.line_end or node.line_start)
            print("=== Source ===")
            for i, line in enumerate(lines[start:end], start=start + 1):
                print(f"{i:4d}| {line}")

    out_edges = [e for e in graph.edges if e.from_node == node.id]
    in_edges = [e for e in graph.edges if e.to_node == node.id]
    print()
    print(f"=== Edges: {len(out_edges)} out, {len(in_edges)} in ===")
    for e in out_edges[:15]:
        target = graph.get_node(e.to_node)
        tname = target.qualified_name if target else e.to_node
        print(f"  -> [{e.type.value}] {tname}")
    return 0
