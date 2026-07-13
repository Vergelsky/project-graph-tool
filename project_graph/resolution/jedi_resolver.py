"""Resolve call targets with Jedi."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import jedi

from project_graph.config import get_repo_root
from project_graph.parsing.extractors import CallInfo, FileAnalysis
from project_graph.resolution.definition_resolver import resolve_call_site


@dataclass
class ResolvedCall:
    caller_qualified_name: str
    callee_text: str
    callee_qualified_name: str | None
    source_file: str | None
    line: int | None
    call_line: int
    call_column: int
    is_await: bool
    resolved: bool
    expandable: bool = False
    def_kind: str | None = None
    unresolved_reason: str | None = None


def clear_jedi_cache() -> None:
    """Clear Jedi and Parso on-disk caches."""
    try:
        from jedi.cache import clear_cache

        clear_cache()
    except Exception:
        pass
    cache_home = Path.home() / ".cache" / "parso"
    if cache_home.exists():
        shutil.rmtree(cache_home, ignore_errors=True)


class JediResolver:
    """Resolve Python calls using Jedi."""

    def __init__(self) -> None:
        self._repo_root = get_repo_root()
        self._project = jedi.Project(path=str(self._repo_root))

    def resolve_call(self, source_file: str, call: CallInfo, source: str | None = None) -> ResolvedCall:
        """Resolve a single call site."""
        if source is None:
            full_path = self._repo_root / source_file
            source = full_path.read_text(encoding="utf-8")
        script = jedi.Script(source, path=str(self._repo_root / source_file), project=self._project)
        try:
            resolved = resolve_call_site(script, call, self._repo_root, source=source)
        except Exception as exc:
            return self._unresolved(call, str(exc))
        if not resolved:
            return self._unresolved(call, "no_definitions")
        if not resolved.expandable:
            return ResolvedCall(
                caller_qualified_name=call.caller_qualified_name,
                callee_text=call.callee_text,
                callee_qualified_name=resolved.qualified_name,
                source_file=resolved.source_file,
                line=resolved.line,
                call_line=call.line,
                call_column=call.column,
                is_await=call.is_await,
                resolved=False,
                expandable=False,
                def_kind=resolved.def_kind,
                unresolved_reason=f"non_expandable:{resolved.def_kind}",
            )
        return ResolvedCall(
            caller_qualified_name=call.caller_qualified_name,
            callee_text=call.callee_text,
            callee_qualified_name=resolved.qualified_name,
            source_file=resolved.source_file,
            line=resolved.line,
            call_line=call.line,
            call_column=call.column,
            is_await=call.is_await,
            resolved=True,
            expandable=True,
            def_kind=resolved.def_kind,
        )

    def resolve_file(self, analysis: FileAnalysis) -> list[ResolvedCall]:
        """Resolve all calls in a file analysis."""
        full_path = self._repo_root / analysis.source_file
        source = full_path.read_text(encoding="utf-8")
        return [self.resolve_call(analysis.source_file, call, source) for call in analysis.calls]

    @staticmethod
    def _unresolved(call: CallInfo, reason: str) -> ResolvedCall:
        """Build unresolved ResolvedCall."""
        return ResolvedCall(
            caller_qualified_name=call.caller_qualified_name,
            callee_text=call.callee_text,
            callee_qualified_name=None,
            source_file=None,
            line=None,
            call_line=call.line,
            call_column=call.column,
            is_await=call.is_await,
            resolved=False,
            expandable=False,
            unresolved_reason=reason,
        )
