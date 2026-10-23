"""Commands: create, trace, describe, serve. They run in one process, in that order."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from project_map.describe import OpenAICompatibleClient, describe_job
from project_map.job import add_entry, create_job, trace_job


def main(argv: list[str] | None = None) -> int:
    """Run one job command."""
    parser = argparse.ArgumentParser(prog="project-map", description="Execution map jobs")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create", help="Create a job folder")
    create_parser.add_argument("job", type=Path)
    create_parser.add_argument("--source", required=True, help="Local directory or git URL")
    create_parser.add_argument("--entry", action="append", required=True, help="file:line or qualified name")
    create_parser.add_argument("--id", help="Job id, defaults to the folder name")

    trace_parser = sub.add_parser("trace", help="Trace entries into execution_graph.json")
    trace_parser.add_argument("job", type=Path)
    trace_parser.add_argument("--entry", action="append", help="Add an entry, then trace all of them")

    describe_parser = sub.add_parser("describe", help="Fill descriptions.json via an OpenAI-compatible API")
    describe_parser.add_argument("job", type=Path)
    describe_parser.add_argument("--base-url", default=os.environ.get("PROJECT_MAP_API_BASE", "https://api.openai.com/v1"))
    describe_parser.add_argument("--model", default=os.environ.get("PROJECT_MAP_MODEL", "gpt-4o-mini"))
    describe_parser.add_argument("--api-key-env", default="PROJECT_MAP_API_KEY")

    serve_parser = sub.add_parser("serve", help="Open the map in the browser")
    serve_parser.add_argument("job", type=Path)
    serve_parser.add_argument("--port", type=int, default=8766)

    cabinet_parser = sub.add_parser("cabinet", help="Open the multi-user cabinet")
    cabinet_parser.add_argument("--data", type=Path, default=Path("data"))
    cabinet_parser.add_argument("--port", type=int, default=8770)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            create_job(args.job, args.source, args.entry, job_id=args.id)
            print(f"Created {args.job}")
            return 0
        if args.command == "trace":
            for value in args.entry or []:
                add_entry(args.job, value)
            graph = trace_job(args.job)
            print(f"Traced {graph.stats()['node_count']} nodes, {graph.stats()['edge_count']} edges")
            return 0
        if args.command == "describe":
            api_key = os.environ.get(args.api_key_env)
            if not api_key:
                print(f"Set {args.api_key_env} to call the description API", file=sys.stderr)
                return 1
            client = OpenAICompatibleClient(args.base_url, api_key, args.model)
            count = describe_job(args.job, client, level="function")
            print(f"Wrote {count} description(s)")
            return 0
        if args.command == "serve":
            from project_map.serve import serve_job

            serve_job(args.job, args.port)
            return 0
        if args.command == "cabinet":
            from project_map.cabinet import serve_cabinet

            serve_cabinet(args.data, args.port)
            return 0
    except (FileExistsError, FileNotFoundError, LookupError, RuntimeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 1
