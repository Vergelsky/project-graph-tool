"""Inspect command."""

from pathlib import Path

import yaml

from project_graph.config import get_data_config_dir, get_output_dir
from project_graph.export.json_exporter import load_graph
from project_graph.models import NodeType


def cmd_inspect(args) -> int:
    """Inspect paths from trace root or validate scenario."""
    output_dir = get_output_dir()
    graph_path = Path(args.output)
    if not graph_path.is_absolute():
        graph_path = output_dir.parent / graph_path
    if not graph_path.exists():
        print(f"Graph not found: {graph_path}. Run trace first.")
        return 1
    graph = load_graph(graph_path)

    root_filter = args.root_id or args.entry
    if not root_filter:
        print("Provide --root-id.")
        return 1

    entry_nodes = [
        n
        for n in graph.nodes
        if n.type == NodeType.ENTRY_POINT
        and (
            root_filter == n.metadata.get("root_id")
            or root_filter in n.qualified_name
            or root_filter in n.name
            or root_filter in (n.metadata.get("resolved_qualified_name") or "")
        )
    ]
    if not entry_nodes:
        print(f"No trace root matching: {root_filter}")
        return 1

    entry = entry_nodes[0]
    label = entry.metadata.get("resolved_qualified_name", entry.qualified_name)
    print(f"Root: {entry.metadata.get('root_id', entry.name)}")
    print(f"Entry: {label}")
    print(f"Node id: {entry.id}")
    subgraph = graph.get_subgraph(entry.id)
    print(f"Reachable nodes: {len(subgraph.nodes)}")

    leaf_types = {NodeType.EXTERNAL_API, NodeType.DATABASE, NodeType.TABLE, NodeType.QUEUE, NodeType.CACHE}
    leaves = [n for n in subgraph.nodes if n.type in leaf_types]
    print(f"Infrastructure leaves: {len(leaves)}")
    for leaf in leaves[:20]:
        print(f"  - [{leaf.type.value}] {leaf.name}")

    if args.check_scenario:
        return _check_scenario(args.check_scenario, subgraph, root_filter)

    return 0


def _check_scenario(scenario_key: str, graph, root_filter: str) -> int:
    """Validate subgraph against reference scenario."""
    ref_path = get_data_config_dir() / "reference_scenarios.yaml"
    if not ref_path.exists():
        print(f"Reference file not found: {ref_path}")
        return 1
    data = yaml.safe_load(ref_path.read_text(encoding="utf-8"))
    scenario = data.get("scenarios", {}).get(scenario_key)
    if not scenario:
        print(f"Scenario not found: {scenario_key}")
        return 1

    expected_root_id = scenario.get("root_id")
    if expected_root_id and expected_root_id != root_filter:
        print(
            f"Scenario '{scenario_key}' expects root_id '{expected_root_id}', "
            f"but inspected '{root_filter}'."
        )
        return 1

    qnames = {n.qualified_name for n in graph.nodes}
    missing_required = []
    for req in scenario.get("required_nodes", []):
        if not any(req in qn for qn in qnames):
            missing_required.append(req)

    max_missing = scenario.get("max_missing", 2)
    if len(missing_required) <= max_missing:
        print(f"Scenario '{scenario_key}': OK ({len(missing_required)} missing required, max {max_missing})")
        if missing_required:
            print("  Missing:", ", ".join(missing_required))
        return 0
    print(f"Scenario '{scenario_key}': FAIL — {len(missing_required)} missing required (max {max_missing})")
    for m in missing_required:
        print(f"  - {m}")
    return 1
