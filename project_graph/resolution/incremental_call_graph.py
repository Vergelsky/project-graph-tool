"""Incrementally expand call graph from trace roots via BFS."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from project_graph.config import MAX_TRACE_DEPTH, get_repo_root
from project_graph.export.json_exporter import load_graph
from project_graph.models import Edge, EdgeType, ExecutionGraph, Node, NodeType
from project_graph.parsing.ast_store import ASTStore
from project_graph.parsing.extractors import CallInfo, DefinitionInfo, FileAnalysis
from project_graph.resolution.jedi_resolver import JediResolver, ResolvedCall
from project_graph.trace_roots.resolver import ResolvedRoot
from project_graph.utils import make_node_id


class IncrementalCallGraphBuilder:
    """Expand call graph on demand from a trace root."""

    def __init__(
        self,
        graph: ExecutionGraph | None = None,
        ast_store: ASTStore | None = None,
        max_depth: int = MAX_TRACE_DEPTH,
    ) -> None:
        self.graph = graph or ExecutionGraph()
        self.ast_store = ast_store or ASTStore()
        self.resolver = JediResolver()
        self.max_depth = max_depth
        self._qname_to_id: dict[str, str] = {
            node.qualified_name: node.id for node in self.graph.nodes if node.qualified_name
        }
        self._visited: set[tuple[str, int, str]] = set()
        for node in self.graph.nodes:
            if node.source_file and node.line_start and node.qualified_name:
                self._visited.add((node.source_file, node.line_start, node.qualified_name))
        self._edge_keys: set[tuple[str, str, str]] = {
            (edge.from_node, edge.to_node, edge.type.value) for edge in self.graph.edges
        }

    @classmethod
    def load_or_empty(cls, path: Path) -> IncrementalCallGraphBuilder:
        """Load incremental cache from disk or start empty."""
        if path.exists():
            return cls(graph=load_graph(path))
        return cls()

    def expand_from(self, resolved: ResolvedRoot) -> None:
        """BFS-expand call graph from a resolved trace root."""
        start_qname = resolved.qualified_name
        start_file = resolved.entry_node.source_file
        start_line = resolved.entry_node.line_start
        if resolved.call_graph_node_id:
            cg_node = self.graph.get_node(resolved.call_graph_node_id)
            if cg_node and cg_node.source_file and cg_node.line_start:
                start_file = cg_node.source_file
                start_line = cg_node.line_start
                start_qname = cg_node.qualified_name
        if not start_file or not start_line:
            raise RuntimeError(f"Cannot expand root without source location: {start_qname}")

        queue: deque[tuple[str, str, int, int]] = deque()
        queue.append((start_qname, start_file, start_line, 0))

        while queue:
            qname, source_file, line_start, depth = queue.popleft()

            analysis = self.ast_store.get_file(source_file)
            if not analysis:
                continue

            defn = self._find_definition(analysis.definitions, qname, line_start)
            if defn:
                qname = defn.qualified_name
                line_end = defn.line_end
            else:
                line_end = line_start

            visit_key = (source_file, line_start, qname)
            if visit_key in self._visited:
                continue
            self._visited.add(visit_key)

            if defn:
                self._ensure_definition_node(defn, source_file)
            else:
                self._ensure_synthetic_node(qname, source_file, line_start)

            caller_id = make_node_id(qname, source_file, line_start)
            self._qname_to_id[qname] = caller_id
            file_source = (get_repo_root() / source_file).read_text(encoding="utf-8")

            for call in self._calls_for_definition(analysis, qname, line_start, line_end):
                resolved_call = self.resolver.resolve_call(source_file, call, file_source)
                self._add_resolved_call(caller_id, resolved_call)
                if depth >= self.max_depth:
                    continue
                if not resolved_call.resolved or not resolved_call.expandable:
                    continue
                callee_qname = resolved_call.callee_qualified_name
                if not callee_qname or not resolved_call.source_file or not resolved_call.line:
                    continue
                callee_qname = self._normalize_callee_qname(
                    callee_qname,
                    resolved_call.source_file,
                    resolved_call.line,
                )
                callee_visit = (resolved_call.source_file, resolved_call.line, callee_qname)
                if callee_visit in self._visited:
                    continue
                queue.append(
                    (callee_qname, resolved_call.source_file, resolved_call.line, depth + 1)
                )

    @staticmethod
    def _calls_for_definition(
        analysis: FileAnalysis,
        qname: str,
        line_start: int,
        line_end: int,
    ) -> list[CallInfo]:
        """Collect calls belonging to a definition."""
        return [
            call
            for call in analysis.calls
            if call.caller_qualified_name == qname
            or (line_start <= call.line <= line_end)
        ]

    def _normalize_callee_qname(self, qname: str, source_file: str, line_start: int) -> str:
        """Align callee qname with AST module-qualified name."""
        analysis = self.ast_store.get_file(source_file)
        if not analysis:
            return qname
        defn = self._find_definition(analysis.definitions, qname, line_start)
        if defn:
            return defn.qualified_name
        return qname

    def _find_definition(
        self,
        definitions: list[DefinitionInfo],
        qname: str,
        line_start: int,
    ) -> DefinitionInfo | None:
        """Find AST definition for qualified name."""
        for defn in definitions:
            if defn.qualified_name == qname:
                return defn
        for defn in definitions:
            if defn.kind in ("function", "method") and defn.line_start == line_start:
                return defn
        return None

    def _ensure_definition_node(self, defn: DefinitionInfo, source_file: str) -> None:
        """Add function/method node from AST definition."""
        node_type = NodeType.METHOD if defn.kind == "method" else NodeType.FUNCTION
        node_id = make_node_id(defn.qualified_name, source_file, defn.line_start)
        self._qname_to_id[defn.qualified_name] = node_id
        self.graph.add_node(
            Node(
                id=node_id,
                type=node_type,
                name=defn.name,
                qualified_name=defn.qualified_name,
                source_file=source_file,
                line_start=defn.line_start,
                line_end=defn.line_end,
                metadata={"decorators": defn.decorators},
            )
        )

    def _ensure_synthetic_node(self, qname: str, source_file: str, line_start: int) -> None:
        """Add synthetic node when AST definition is missing."""
        node_id = make_node_id(qname, source_file, line_start)
        if not self.graph.get_node(node_id):
            self.graph.add_node(
                Node(
                    id=node_id,
                    type=NodeType.FUNCTION,
                    name=qname.split(".")[-1],
                    qualified_name=qname,
                    source_file=source_file,
                    line_start=line_start,
                    metadata={"synthetic": True},
                )
            )

    def _add_resolved_call(self, caller_id: str, call: ResolvedCall) -> None:
        """Add call edge from resolved Jedi result."""
        if call.resolved and call.expandable and call.callee_qualified_name and call.source_file and call.line:
            callee_id = make_node_id(call.callee_qualified_name, call.source_file, call.line)
            if not self.graph.get_node(callee_id):
                self.graph.add_node(
                    Node(
                        id=callee_id,
                        type=NodeType.UNKNOWN,
                        name=call.callee_qualified_name.split(".")[-1],
                        qualified_name=call.callee_qualified_name,
                        source_file=call.source_file,
                        line_start=call.line,
                        metadata={"synthetic": True},
                    )
                )
            edge_type = EdgeType.AWAITS if call.is_await else EdgeType.CALLS
            self._add_edge_if_absent(
                Edge(
                    from_node=caller_id,
                    to_node=callee_id,
                    type=edge_type,
                    metadata={"callee_text": call.callee_text, "call_line": call.call_line},
                )
            )
            return

        if call.callee_qualified_name and call.source_file and call.line and not call.expandable:
            callee_id = make_node_id(call.callee_qualified_name, call.source_file, call.line)
            if not self.graph.get_node(callee_id):
                self.graph.add_node(
                    Node(
                        id=callee_id,
                        type=NodeType.UNKNOWN,
                        name=call.callee_qualified_name.split(".")[-1],
                        qualified_name=call.callee_qualified_name,
                        source_file=call.source_file,
                        line_start=call.line,
                        metadata={"synthetic": True, "def_kind": call.def_kind},
                    )
                )
            self._add_edge_if_absent(
                Edge(
                    from_node=caller_id,
                    to_node=callee_id,
                    type=EdgeType.DEPENDS_ON,
                    metadata={
                        "callee_text": call.callee_text,
                        "reason": call.unresolved_reason or "non_expandable",
                        "call_line": call.call_line,
                    },
                )
            )
            return

        unknown_id = make_node_id(f"UNRESOLVED:{call.callee_text}")
        if not self.graph.get_node(unknown_id):
            self.graph.add_node(
                Node(
                    id=unknown_id,
                    type=NodeType.UNKNOWN,
                    name=call.callee_text,
                    qualified_name=call.callee_text,
                    metadata={"unresolved": True},
                )
            )
        self._add_edge_if_absent(
            Edge(
                from_node=caller_id,
                to_node=unknown_id,
                type=EdgeType.DEPENDS_ON,
                metadata={
                    "callee_text": call.callee_text,
                    "reason": call.unresolved_reason,
                    "call_line": call.call_line,
                },
            )
        )

    def _add_edge_if_absent(self, edge: Edge) -> None:
        """Add edge deduplicated by from/to/type."""
        key = (edge.from_node, edge.to_node, edge.type.value)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.graph.add_edge(edge)

    def unresolved_ratio(self) -> float:
        """Return ratio of DEPENDS_ON edges to total outgoing call edges."""
        total = 0
        unresolved = 0
        for edge in self.graph.edges:
            if edge.type in (EdgeType.CALLS, EdgeType.AWAITS, EdgeType.DEPENDS_ON):
                total += 1
                if edge.type == EdgeType.DEPENDS_ON:
                    unresolved += 1
        return unresolved / total if total else 0.0
