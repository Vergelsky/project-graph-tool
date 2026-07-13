"""Build call graph from resolved calls."""

from __future__ import annotations

from project_graph.models import Edge, EdgeType, ExecutionGraph, Node, NodeType
from project_graph.parsing.ast_store import ASTStore
from project_graph.resolution.jedi_resolver import JediResolver, ResolvedCall
from project_graph.utils import make_node_id


class CallGraphBuilder:
    """Build a call graph from AST and Jedi resolution."""

    def __init__(self, ast_store: ASTStore | None = None) -> None:
        self.ast_store = ast_store or ASTStore()
        self.resolver = JediResolver()
        self.graph = ExecutionGraph()
        self._qname_to_id: dict[str, str] = {}

    def build(self, source_files: list[str] | None = None) -> ExecutionGraph:
        """Build call graph for all or selected files."""
        if source_files is None:
            analyses = self.ast_store.analyze_all()
        else:
            analyses = {}
            for sf in source_files:
                result = self.ast_store.get_file(sf)
                if result:
                    analyses[sf] = result

        for source_file, analysis in analyses.items():
            for defn in analysis.definitions:
                node_type = NodeType.METHOD if defn.kind == "method" else NodeType.FUNCTION
                if defn.kind == "class":
                    node_type = NodeType.MODEL
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

        resolved_calls: list[ResolvedCall] = []
        for source_file, analysis in analyses.items():
            resolved_calls.extend(self.resolver.resolve_file(analysis))

        for call in resolved_calls:
            caller_id = self._qname_to_id.get(
                call.caller_qualified_name,
                make_node_id(call.caller_qualified_name),
            )
            if not self.graph.get_node(caller_id):
                self._qname_to_id[call.caller_qualified_name] = caller_id
                self.graph.add_node(
                    Node(
                        id=caller_id,
                        type=NodeType.FUNCTION,
                        name=call.caller_qualified_name.split(".")[-1],
                        qualified_name=call.caller_qualified_name,
                        metadata={"synthetic": True},
                    )
                )
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
                self.graph.add_edge(
                    Edge(
                        from_node=caller_id,
                        to_node=callee_id,
                        type=edge_type,
                        metadata={"callee_text": call.callee_text, "call_line": call.call_line},
                    )
                )
            else:
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
                self.graph.add_edge(
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
        return self.graph

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

    @property
    def qname_to_id(self) -> dict[str, str]:
        """Return qualified name to node id map."""
        return dict(self._qname_to_id)
