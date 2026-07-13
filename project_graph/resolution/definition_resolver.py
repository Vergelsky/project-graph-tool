"""Normalize Jedi results to project definition sites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import jedi

from project_graph.parsing.extractors import CallInfo

_EXTERNAL_MARKERS = (
    "site-packages",
    "typeshed",
    ".venv",
    "venv",
    "dist-packages",
)

_EXPANDABLE_KINDS = frozenset({"function", "method"})


@dataclass
class ResolvedDefinition:
    """A resolved symbol pointing at a definition site."""

    qualified_name: str
    source_file: str
    line: int
    def_kind: str
    expandable: bool


def is_project_definition(defn, repo_root: Path) -> bool:
    """Return True if Jedi definition is inside the analyzed project."""
    module_path = getattr(defn, "module_path", None)
    if not module_path:
        return False
    path_str = str(module_path).replace("\\", "/")
    if any(marker in path_str for marker in _EXTERNAL_MARKERS):
        return False
    try:
        module_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return path_str.endswith(".py")


def relative_source_file(defn, repo_root: Path) -> str | None:
    """Convert Jedi module_path to repo-relative path."""
    module_path = getattr(defn, "module_path", None)
    if not module_path:
        return None
    try:
        return str(module_path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(module_path).replace("\\", "/")


def jedi_definition_to_resolved(defn, repo_root: Path) -> ResolvedDefinition | None:
    """Map a Jedi Name to ResolvedDefinition."""
    if not is_project_definition(defn, repo_root):
        return None
    source_file = relative_source_file(defn, repo_root)
    if not source_file:
        return None
    try:
        def_kind = defn.type or "statement"
    except Exception:
        def_kind = "statement"
    module = defn.module_name or ""
    name = defn.name or ""
    qname = defn.full_name or name
    if module and name:
        if qname == name or not qname.startswith(f"{module}."):
            qname = f"{module}.{name}"
    line = defn.line or 1
    expandable = def_kind in _EXPANDABLE_KINDS
    return ResolvedDefinition(
        qualified_name=qname,
        source_file=source_file,
        line=line,
        def_kind=def_kind,
        expandable=expandable,
    )


def _definition_score(defn: ResolvedDefinition, callee_text: str) -> int:
    """Score definition candidates; higher is better."""
    score = 0
    if defn.def_kind in _EXPANDABLE_KINDS:
        score += 100
    elif defn.def_kind == "class":
        score += 20
    else:
        score += 5
    if defn.expandable:
        score += 50
    callee_tail = callee_text.rsplit(".", 1)[-1] if "." in callee_text else callee_text
    if defn.qualified_name.endswith(f".{callee_tail}") or defn.qualified_name == callee_tail:
        score += 40
    if callee_text and (defn.qualified_name == callee_text or defn.qualified_name.endswith(f".{callee_text}")):
        score += 30
    return score


def pick_best_definition(
    candidates: list[ResolvedDefinition],
    callee_text: str,
) -> ResolvedDefinition | None:
    """Pick the best resolved definition from candidates."""
    if not candidates:
        return None
    unique: dict[tuple[str, str, int], ResolvedDefinition] = {}
    for candidate in candidates:
        key = (candidate.qualified_name, candidate.source_file, candidate.line)
        existing = unique.get(key)
        if existing is None or _definition_score(candidate, callee_text) > _definition_score(existing, callee_text):
            unique[key] = candidate
    return max(unique.values(), key=lambda item: _definition_score(item, callee_text))


def _collect_jedi_names(script: jedi.Script, line: int, column: int) -> list:
    """Collect goto and infer names at a position."""
    names: list = []
    try:
        names.extend(script.goto(line, column, follow_imports=True))
    except Exception:
        pass
    try:
        names.extend(script.infer(line, column))
    except Exception:
        pass
    return names


def _method_column(callee_text: str, line_text: str, callee_column: int) -> int | None:
    """Find column of .method suffix in callee_text on source line."""
    if "." not in callee_text:
        return None
    method_name = callee_text.rsplit(".", 1)[-1]
    dot_marker = f".{method_name}"
    idx = line_text.find(dot_marker, max(0, callee_column))
    if idx < 0:
        idx = line_text.find(dot_marker)
    if idx < 0:
        return None
    return idx + len(dot_marker) - len(method_name)


def resolve_at_position(
    script: jedi.Script,
    line: int,
    column: int,
    repo_root: Path,
    *,
    callee_text: str = "",
) -> ResolvedDefinition | None:
    """Resolve symbol at line/column to a project definition."""
    candidates: list[ResolvedDefinition] = []
    for defn in _collect_jedi_names(script, line, column):
        resolved = jedi_definition_to_resolved(defn, repo_root)
        if resolved:
            candidates.append(resolved)
    return pick_best_definition(candidates, callee_text)


def resolve_class_method(
    class_resolved: ResolvedDefinition,
    method_name: str,
    repo_root: Path,
) -> ResolvedDefinition | None:
    """Resolve Class.method when goto landed on the class definition."""
    full_path = repo_root / class_resolved.source_file
    if not full_path.exists():
        return None
    source = full_path.read_text(encoding="utf-8")
    class_name = class_resolved.qualified_name.split(".")[-1]
    stub = f"from {class_resolved.qualified_name.rsplit('.', 1)[0]} import {class_name}\n{class_name}.{method_name}"
    script = jedi.Script(source, path=str(full_path), project=jedi.Project(path=str(repo_root)))
    try:
        column = len(class_name) + 1
        names = script.goto(2, column, follow_imports=True)
    except Exception:
        names = []
    candidates: list[ResolvedDefinition] = []
    for defn in names:
        resolved = jedi_definition_to_resolved(defn, repo_root)
        if resolved:
            candidates.append(resolved)
    if not candidates:
        line_texts = source.splitlines()
        for line_no, line_text in enumerate(line_texts, start=1):
            if f"def {method_name}" in line_text or f"async def {method_name}" in line_text:
                col = line_text.find(method_name)
                if col >= 0:
                    at_pos = resolve_at_position(
                        script,
                        line_no,
                        col + 1,
                        repo_root,
                        callee_text=f"{class_name}.{method_name}",
                    )
                    if at_pos:
                        candidates.append(at_pos)
    return pick_best_definition(candidates, f"{class_name}.{method_name}")


def resolve_call_site(
    script: jedi.Script,
    call: CallInfo,
    repo_root: Path,
    *,
    source: str | None = None,
) -> ResolvedDefinition | None:
    """Resolve a call site to the callee definition in the project."""
    if source is None:
        return None
    line_text = source.splitlines()[call.line - 1] if 0 < call.line <= len(source.splitlines()) else ""

    positions: list[int] = []
    for col in (call.callee_column, call.column):
        if col not in positions:
            positions.append(col)
    method_col = _method_column(call.callee_text, line_text, call.callee_column or call.column)
    if method_col is not None and method_col not in positions:
        positions.append(method_col)

    candidates: list[ResolvedDefinition] = []
    for column in positions:
        resolved = resolve_at_position(
            script,
            call.line,
            column,
            repo_root,
            callee_text=call.callee_text,
        )
        if resolved:
            candidates.append(resolved)

    best = pick_best_definition(candidates, call.callee_text)
    if best and best.def_kind == "class" and "." in call.callee_text:
        method_name = call.callee_text.rsplit(".", 1)[-1]
        method_resolved = resolve_class_method(best, method_name, repo_root)
        if method_resolved:
            return method_resolved
    return best
