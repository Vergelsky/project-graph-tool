"""CLI entry point."""

import argparse
import sys

from project_graph.config import WorkspaceNotConfiguredError, init_workspace


def _pop_workspace_arg(argv: list[str]) -> str | None:
    """Extract and remove --workspace from argv."""
    if "--workspace" not in argv:
        return None
    idx = argv.index("--workspace")
    if idx + 1 >= len(argv):
        raise WorkspaceNotConfiguredError("--workspace requires a path argument")
    workspace = argv[idx + 1]
    del argv[idx : idx + 2]
    return workspace


def main(argv: list[str] | None = None) -> int:
    """Run CLI command."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        init_workspace(_pop_workspace_arg(argv))
    except WorkspaceNotConfiguredError as exc:
        print(exc, file=sys.stderr)
        return 1

    from project_graph.cli.describe import cmd_describe_node
    from project_graph.cli.export import cmd_export
    from project_graph.cli.inspect import cmd_inspect
    from project_graph.cli.trace import cmd_trace

    parser = argparse.ArgumentParser(prog="project-graph", description="Project Execution Map builder")
    sub = parser.add_subparsers(dest="command", required=True)

    trace_parser = sub.add_parser("trace", help="Trace explicit roots into execution graph")
    trace_parser.add_argument("--def", dest="defs", action="append", help="Definition pointer (file:line or qname)")
    trace_parser.add_argument("--call", dest="calls", action="append", help="Call site pointer (file:line)")
    trace_parser.add_argument("--file", help="YAML file with roots list")
    trace_parser.add_argument("--id", help="Root id for a single --def pointer")
    trace_parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Also append explicit CLI pointers to trace_queue.yaml",
    )
    trace_parser.add_argument(
        "--reset-call-graph",
        action="store_true",
        help="Clear incremental call_graph.json cache before tracing",
    )
    trace_parser.add_argument(
        "--clear-jedi-cache",
        action="store_true",
        help="Clear Jedi/Parso disk cache before tracing",
    )

    export_parser = sub.add_parser("export", help="Export execution graph JSON")
    export_parser.add_argument("-o", "--output", default="output/execution_graph.json")

    inspect_parser = sub.add_parser("inspect", help="Inspect paths from a trace root")
    inspect_parser.add_argument("--root-id", help="Trace root id")
    inspect_parser.add_argument("--entry", help="Deprecated alias for --root-id")
    inspect_parser.add_argument("--check-scenario", help="Validate against reference_scenarios.yaml key")
    inspect_parser.add_argument("--output", default="output/execution_graph.json")

    describe_parser = sub.add_parser("describe-node", help="Print node context for AI description")
    describe_parser.add_argument("node_id", help="Node id or qualified_name fragment")
    describe_parser.add_argument("--output", default="output/execution_graph.json")

    args = parser.parse_args(argv)

    if args.command == "trace":
        return cmd_trace(args)
    if args.command == "export":
        return cmd_export(args)
    if args.command == "inspect":
        return cmd_inspect(args)
    if args.command == "describe-node":
        return cmd_describe_node(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
