"""One resolved call site. The tracer stores this, not a Jedi object."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ResolvedCall:
    """Where a call goes, and whether the walk should enter it."""

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
