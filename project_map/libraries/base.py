"""Seam for library modules. The tracer asks bridges where a library call re-enters project code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class SeenCall:
    """What a bridge sees at a call site. Library modules do not receive the Jedi script."""

    callee_text: str
    expandable: bool
    argument_names: list[str] = field(default_factory=list)
    caller_file: str | None = None


@dataclass(frozen=True)
class ProjectTarget:
    """A project function the tracer should keep walking."""

    qualified_name: str
    source_file: str
    line: int


class ProjectIndex:
    """Definitions collected once per trace. Bridges only read it."""

    def __init__(self) -> None:
        self.by_name: dict[str, list[ProjectTarget]] = {}
        self.by_qualified_name: dict[str, ProjectTarget] = {}

    def add(self, target: ProjectTarget) -> None:
        """Index one function or method."""
        self.by_qualified_name[target.qualified_name] = target
        name = target.qualified_name.rsplit(".", 1)[-1]
        self.by_name.setdefault(name, []).append(target)

    def named(self, name: str, *, prefer_file: str | None = None) -> list[ProjectTarget]:
        """Return functions with this short name, same file first."""
        found = list(self.by_name.get(name, []))
        if prefer_file:
            found.sort(key=lambda item: item.source_file != prefer_file)
        return found


class LibraryBridge(Protocol):
    """Answer: does this library call continue inside the project?"""

    name: str

    def extra_targets(self, call: SeenCall, index: ProjectIndex) -> list[ProjectTarget]:
        """Return project functions to enqueue. Empty when the call is a real leaf."""
