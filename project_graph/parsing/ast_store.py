"""Cache parsed file analyses."""

from __future__ import annotations

import json
from pathlib import Path

from project_graph.config import EXCLUDE_DIRS, EXCLUDE_FILE_PATTERNS, get_cache_dir, get_repo_root
from project_graph.parsing.extractors import FileAnalysis, analyze_file
from project_graph.parsing.tree_sitter_parser import parse_source


class ASTStore:
    """Store and cache per-file AST analyses."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or get_cache_dir() / "ast"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory: dict[str, FileAnalysis] = {}

    def iter_python_files(self) -> list[Path]:
        """List Python files to analyze."""
        repo_root = get_repo_root()
        files: list[Path] = []
        for path in repo_root.rglob("*.py"):
            parts = set(path.parts)
            if parts & EXCLUDE_DIRS:
                continue
            rel = path.relative_to(repo_root)
            name = path.name
            if any(name.startswith(p) or name.endswith(p.replace("test_", "")) for p in EXCLUDE_FILE_PATTERNS):
                if "test" in name:
                    continue
            files.append(path)
        return sorted(files)

    def analyze_all(self, force: bool = False) -> dict[str, FileAnalysis]:
        """Analyze all Python files."""
        repo_root = get_repo_root()
        for path in self.iter_python_files():
            rel = str(path.relative_to(repo_root)).replace("\\", "/")
            self.get_file(rel, force=force)
        return dict(self._memory)

    def get_file(self, source_file: str, force: bool = False) -> FileAnalysis | None:
        """Get or compute analysis for a file."""
        if not force and source_file in self._memory:
            return self._memory[source_file]
        full_path = get_repo_root() / source_file
        if not full_path.exists():
            return None
        mtime = full_path.stat().st_mtime
        cache_path = self.cache_dir / (source_file.replace("/", "__") + ".json")
        if not force and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("mtime") == mtime:
                analysis = _analysis_from_dict(cached)
                self._memory[source_file] = analysis
                return analysis
        source = full_path.read_text(encoding="utf-8")
        tree = parse_source(source)
        analysis = analyze_file(source_file, source, tree)
        self._memory[source_file] = analysis
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({**_analysis_to_dict(analysis), "mtime": mtime}, indent=2),
            encoding="utf-8",
        )
        return analysis


def _analysis_to_dict(analysis: FileAnalysis) -> dict:
    """Serialize FileAnalysis."""
    return {
        "source_file": analysis.source_file,
        "module": analysis.module,
        "definitions": [d.__dict__ for d in analysis.definitions],
        "calls": [c.__dict__ for c in analysis.calls],
    }


def _analysis_from_dict(data: dict) -> FileAnalysis:
    """Deserialize FileAnalysis."""
    from project_graph.parsing.extractors import DefinitionInfo

    return FileAnalysis(
        source_file=data["source_file"],
        module=data["module"],
        definitions=[DefinitionInfo(**d) for d in data.get("definitions", [])],
        calls=[_call_info_from_dict(c) for c in data.get("calls", [])],
    )


def _call_info_from_dict(data: dict) -> CallInfo:
    """Deserialize CallInfo with backward-compatible callee_column."""
    from project_graph.parsing.extractors import CallInfo

    column = data["column"]
    callee_column = data.get("callee_column", column)
    return CallInfo(
        caller_qualified_name=data["caller_qualified_name"],
        callee_text=data["callee_text"],
        line=data["line"],
        column=column,
        callee_column=callee_column,
        is_await=data.get("is_await", False),
    )
