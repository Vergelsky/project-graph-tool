"""Resolve trace pointers to call graph nodes."""

from __future__ import annotations

from dataclasses import dataclass

import jedi

from project_graph.config import get_repo_root
from project_graph.models import ExecutionGraph, Node, NodeType
from project_graph.parsing.ast_store import ASTStore
from project_graph.parsing.extractors import DefinitionInfo
from project_graph.resolution.jedi_resolver import JediResolver
from project_graph.trace_roots.models import TracePointer, TraceRoot
from project_graph.trace_roots.store import TraceStore, default_root_id
from project_graph.utils import make_node_id


class RootResolveError(RuntimeError):
    """Raised when a trace pointer cannot be resolved."""


@dataclass
class ResolvedRoot:
    """Resolved trace root with entry and call-graph start node."""

    root: TraceRoot
    root_id: str
    qualified_name: str
    call_graph_node_id: str
    entry_node: Node


class RootResolver:
    """Resolve TracePointer to call graph entry nodes."""

    def __init__(self, call_graph: ExecutionGraph, ast_store: ASTStore | None = None) -> None:
        self.call_graph = call_graph
        self.ast_store = ast_store or ASTStore()
        self.jedi_resolver = JediResolver()
        self._repo_root = get_repo_root()
        self._qname_to_id = {node.qualified_name: node.id for node in call_graph.nodes}

    def resolve(self, root: TraceRoot) -> ResolvedRoot:
        """Resolve a trace root pointer."""
        pointer = root.pointer
        if pointer.kind == "def" and pointer.qualified_name:
            qualified_name, source_file, line_start = self._resolve_def_by_qname(pointer.qualified_name)
        elif pointer.kind == "def" and pointer.file and pointer.line:
            qualified_name, source_file, line_start = self._resolve_def_at_line(pointer.file, pointer.line)
        elif pointer.kind == "call" and pointer.file and pointer.line:
            qualified_name, source_file, line_start = self._resolve_call_at_line(pointer.file, pointer.line)
        else:
            raise RootResolveError(f"Invalid pointer: {pointer}")

        call_graph_node_id = self._find_call_graph_node_id(qualified_name, source_file, line_start)
        root_id = TraceStore.ensure_id(root)
        entry_node = Node(
            id=make_node_id(f"ROOT:{root_id}"),
            type=NodeType.ENTRY_POINT,
            name=root_id,
            qualified_name=qualified_name,
            source_file=source_file,
            line_start=line_start,
            metadata={
                "root_id": root_id,
                "pointer_kind": pointer.kind,
                "resolved_qualified_name": qualified_name,
                "call_graph_node_id": call_graph_node_id,
            },
        )
        return ResolvedRoot(
            root=root,
            root_id=root_id,
            qualified_name=qualified_name,
            call_graph_node_id=call_graph_node_id,
            entry_node=entry_node,
        )

    def _resolve_def_by_qname(self, qualified_name: str) -> tuple[str, str | None, int | None]:
        """Resolve definition by qualified name."""
        for node in self.call_graph.nodes:
            if node.qualified_name == qualified_name:
                return node.qualified_name, node.source_file, node.line_start
        ast_match = self._find_definition_in_ast(qualified_name)
        if ast_match:
            return ast_match
        inherited = self._resolve_inherited_method(qualified_name)
        if inherited:
            return inherited
        raise RootResolveError(
            f"Definition not found: {qualified_name}. "
            "Ensure the pointer file and line are correct."
        )

    def _find_definition_in_ast(self, qualified_name: str) -> tuple[str, str, int] | None:
        """Find exact qualified name in AST definitions."""
        parts = qualified_name.split(".")
        for module_len in range(len(parts) - 1, 0, -1):
            module = ".".join(parts[:module_len])
            rel = module.replace(".", "/") + ".py"
            analysis = self.ast_store.get_file(rel)
            if not analysis:
                continue
            for defn in analysis.definitions:
                if defn.qualified_name == qualified_name:
                    return defn.qualified_name, rel, defn.line_start
        return None

    def _resolve_inherited_method(self, qualified_name: str) -> tuple[str, str, int] | None:
        """Resolve inherited method via Jedi stub import."""
        parts = qualified_name.split(".")
        if len(parts) < 3:
            return None
        method_name = parts[-1]
        class_qname = ".".join(parts[:-1])
        class_parts = class_qname.split(".")
        class_name = class_parts[-1]
        module = ".".join(class_parts[:-1])
        rel = module.replace(".", "/") + ".py"
        full_path = self._repo_root / rel
        if not full_path.exists():
            return None
        stub = f"from {module} import {class_name}\n{class_name}.{method_name}"
        script = jedi.Script(stub, path=str(full_path), project=jedi.Project(path=str(self._repo_root)))
        try:
            definitions = script.goto(2, len(class_name) + 1)
        except Exception:
            return None
        if not definitions:
            return None
        defn = definitions[0]
        qname = defn.full_name or qualified_name
        rel_path = self._relative_path(defn.module_path) or rel
        return qname, rel_path, defn.line or 1

    def _resolve_def_at_line(self, source_file: str, line: int) -> tuple[str, str, int]:
        """Resolve enclosing definition at file line."""
        analysis = self.ast_store.get_file(source_file)
        if not analysis:
            raise RootResolveError(f"File not found: {source_file}")
        defn = self._find_enclosing_definition(analysis.definitions, line)
        if defn:
            return defn.qualified_name, source_file, defn.line_start
        resolved = self._jedi_goto(source_file, line)
        if resolved:
            return resolved
        raise RootResolveError(f"No definition at {source_file}:{line}")

    def _resolve_call_at_line(self, source_file: str, line: int) -> tuple[str, str | None, int | None]:
        """Resolve callee at call site line."""
        analysis = self.ast_store.get_file(source_file)
        if not analysis:
            raise RootResolveError(f"File not found: {source_file}")
        calls = [call for call in analysis.calls if call.line == line]
        if not calls:
            calls = sorted(
                [call for call in analysis.calls if abs(call.line - line) <= 1],
                key=lambda call: abs(call.line - line),
            )
        if not calls:
            raise RootResolveError(f"No call at {source_file}:{line}")
        resolved_call = self.jedi_resolver.resolve_call(source_file, calls[0])
        if not resolved_call.resolved or not resolved_call.callee_qualified_name:
            reason = resolved_call.unresolved_reason or "unresolved callee"
            raise RootResolveError(f"Call at {source_file}:{line} unresolved: {reason}")
        return (
            resolved_call.callee_qualified_name,
            resolved_call.source_file,
            resolved_call.line,
        )

    def _find_call_graph_node_id(
        self,
        qualified_name: str,
        source_file: str | None,
        line_start: int | None,
    ) -> str:
        """Find matching node id in call graph."""
        if qualified_name in self._qname_to_id:
            return self._qname_to_id[qualified_name]
        for node in self.call_graph.nodes:
            if node.qualified_name == qualified_name:
                return node.id
            if source_file and node.source_file == source_file and node.line_start == line_start:
                return node.id
        return make_node_id(qualified_name, source_file, line_start)

    def _find_enclosing_definition(
        self,
        definitions: list[DefinitionInfo],
        line: int,
    ) -> DefinitionInfo | None:
        """Find innermost function/method definition containing line."""
        matches = [
            defn
            for defn in definitions
            if defn.kind in ("function", "method")
            and defn.line_start <= line <= defn.line_end
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda defn: (defn.line_end - defn.line_start, -defn.line_start))[0]

    def _jedi_goto(self, source_file: str, line: int) -> tuple[str, str, int] | None:
        """Resolve symbol at line via Jedi."""
        full_path = self._repo_root / source_file
        source = full_path.read_text(encoding="utf-8")
        line_text = source.splitlines()[line - 1] if 0 < line <= len(source.splitlines()) else ""
        column = len(line_text) - len(line_text.lstrip()) + 1
        script = jedi.Script(source, path=str(full_path), project=jedi.Project(path=str(self._repo_root)))
        try:
            definitions = script.goto(line, column)
        except Exception:
            return None
        if not definitions:
            return None
        defn = definitions[0]
        module = defn.module_name or ""
        name = defn.name or ""
        qname = defn.full_name or (f"{module}.{name}" if module else name)
        rel_path = self._relative_path(defn.module_path) or source_file
        return qname, rel_path, defn.line or line

    def _relative_path(self, module_path) -> str | None:
        """Convert absolute path to repo-relative."""
        if not module_path:
            return None
        try:
            return str(module_path.relative_to(self._repo_root)).replace("\\", "/")
        except ValueError:
            return str(module_path)

