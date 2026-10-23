"""One-pass index of project functions for library bridges."""

from __future__ import annotations

from pathlib import Path

from project_map.parse.extract import analyze_file
from project_map.parse.tree import parse_source

from project_map.analyze.files import iter_python_files, read_text
from project_map.libraries.base import ProjectIndex, ProjectTarget


def build_index(repo: Path) -> ProjectIndex:
    """Index function and method definitions in the project."""
    index = ProjectIndex()
    for path in iter_python_files(repo):
        rel = path.relative_to(repo).as_posix()
        source = read_text(path)
        if source is None:
            continue
        analysis = analyze_file(rel, source, parse_source(source))
        for defn in analysis.definitions:
            if defn.kind not in ("function", "method"):
                continue
            index.add(
                ProjectTarget(
                    qualified_name=defn.qualified_name,
                    source_file=rel,
                    line=defn.line_start,
                )
            )
    return index
