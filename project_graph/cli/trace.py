"""Trace command."""

from __future__ import annotations

from pathlib import Path

from project_graph.config import get_data_config_dir
from project_graph.pipeline import trace_roots
from project_graph.trace_roots.models import TraceRoot
from project_graph.trace_roots.store import TraceStore, parse_cli_pointer


def cmd_trace(args) -> int:
    """Run trace for explicit roots."""
    store = TraceStore()
    roots: list[TraceRoot] = []

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = get_data_config_dir().parent / file_path
        roots = store.load_roots_file(file_path)
        if not roots:
            print(f"No roots in file: {file_path}")
            return 1
    elif args.defs or args.calls:
        for value in args.defs or []:
            pointer = parse_cli_pointer("def", value)
            roots.append(TraceRoot(id=args.id if args.id and len(args.defs) == 1 else None, pointer=pointer))
        for value in args.calls or []:
            roots.append(TraceRoot(pointer=parse_cli_pointer("call", value)))
    else:
        roots = store.load_queue()
        if not roots:
            print("No roots in trace_queue.yaml and no --def/--call/--file provided.")
            return 1

    if args.enqueue and (args.defs or args.calls):
        explicit_roots = []
        for value in args.defs or []:
            explicit_roots.append(TraceRoot(id=args.id, pointer=parse_cli_pointer("def", value)))
        for value in args.calls or []:
            explicit_roots.append(TraceRoot(pointer=parse_cli_pointer("call", value)))
        store.append_to_queue(explicit_roots)

    from_queue = not (args.defs or args.calls or args.file)
    result = trace_roots(
        roots,
        reset_call_graph=args.reset_call_graph,
        clear_jedi_cache_flag=args.clear_jedi_cache,
        from_queue=from_queue,
    )
    if result.stats.get("errors"):
        return 1
    print(
        f"Done. Processed {len(result.processed_roots)} root(s). "
        f"Execution graph: {result.execution_graph.stats()['node_count']} nodes."
    )
    return 0
