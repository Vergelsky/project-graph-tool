"""Export command."""

from pathlib import Path

from project_graph.config import get_output_dir
from project_graph.export.json_exporter import export_graph, load_graph


def cmd_export(args) -> int:
    """Re-export graph from existing execution_graph.json."""
    output_dir = get_output_dir()
    src = output_dir / "execution_graph.json"
    if not src.exists():
        print(f"No graph found at {src}. Run build first.")
        return 1
    graph = load_graph(src)
    dest = Path(args.output)
    if not dest.is_absolute():
        dest = output_dir.parent / dest
    export_graph(graph, dest)
    print(f"Exported to {dest}")
    return 0
