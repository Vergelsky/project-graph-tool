"""Jedi resolution bound to an explicit repository path."""

from __future__ import annotations

from pathlib import Path

import jedi

from project_map.analyze.definitions import resolve_call_site
from project_map.analyze.resolved import ResolvedCall
from project_map.parse.extract import CallInfo


class JediResolver:
    """Resolve calls inside one checkout. No process-global workspace."""

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._project = jedi.Project(path=str(repo))

    def resolve_call(self, source_file: str, call: CallInfo, source: str) -> ResolvedCall:
        """Resolve one call site to a definition inside the repository."""
        script = jedi.Script(source, path=str(self._repo / source_file), project=self._project)
        try:
            resolved = resolve_call_site(script, call, self._repo, source=source)
        except Exception as exc:
            return _unresolved(call, str(exc))
        if not resolved:
            return _unresolved(call, "no_definitions")
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


def _unresolved(call: CallInfo, reason: str) -> ResolvedCall:
    """Build an unresolved call result."""
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
