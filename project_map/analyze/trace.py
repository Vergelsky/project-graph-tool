"""Walk project calls until a library boundary. Depth is not capped."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from project_map.analyze.resolved import ResolvedCall
from project_map.ids import make_node_id
from project_map.models import Edge, EdgeType, Node, NodeType
from project_map.parse.extract import DefinitionInfo, analyze_file
from project_map.parse.tree import parse_source

from project_map.analyze.arguments import argument_names
from project_map.analyze.files import read_text
from project_map.analyze.index import build_index
from project_map.analyze.resolver import JediResolver
from project_map.graph import MapGraph
from project_map.libraries.base import LibraryBridge, ProjectIndex, ProjectTarget, SeenCall
from project_map.libraries import default_bridges

ExpandedKey = tuple[str, int, str]


class ExecutionTracer:
    """BFS from entry points. Unchanged files are not resolved again."""

    def __init__(
        self,
        repo: Path,
        graph: MapGraph | None = None,
        *,
        bridges: list[LibraryBridge] | None = None,
        resolver: JediResolver | None = None,
        file_hashes: dict[str, str] | None = None,
        expanded: set[ExpandedKey] | None = None,
        current_hashes: dict[str, str] | None = None,
    ) -> None:
        self.repo = repo
        self.graph = graph or MapGraph()
        self.bridges = default_bridges() if bridges is None else bridges
        self.resolver = resolver or JediResolver(repo)
        self.file_hashes = dict(file_hashes or {})
        self.expanded = set(expanded or set())
        self.current_hashes = dict(current_hashes or {})
        self.index: ProjectIndex = build_index(repo)
        self._analyses: dict[str, object] = {}

    def invalidate_changed_files(self) -> None:
        """Drop nodes whose source file hash no longer matches the checkout."""
        stale = {
            path
            for path in set(self.file_hashes) | set(self.current_hashes)
            if self.file_hashes.get(path) != self.current_hashes.get(path)
        }
        if not stale:
            return
        node_ids = {node.id for node in self.graph.nodes if node.source_file in stale}
        self.graph.remove_nodes(node_ids)
        self.expanded = {key for key in self.expanded if key[0] not in stale}

    def expand(self, target: ProjectTarget) -> None:
        """Walk target and every project function it reaches."""
        queue: deque[ProjectTarget] = deque([target])
        seen: set[ExpandedKey] = set()
        while queue:
            current = queue.popleft()
            key = (current.source_file, current.line, current.qualified_name)
            if key in seen:
                continue
            seen.add(key)
            definition = self._definition(current)
            self._ensure_node(current, definition)
            node_id = _node_id(current, definition)
            if key in self.expanded and self.file_hashes.get(current.source_file) == self.current_hashes.get(
                current.source_file
            ):
                queue.extend(self._stored_children(node_id))
                continue
            queue.extend(self._resolve_body(current, definition, node_id))
            self.expanded.add(key)
            if current.source_file in self.current_hashes:
                self.file_hashes[current.source_file] = self.current_hashes[current.source_file]

    def _resolve_body(
        self,
        target: ProjectTarget,
        definition: DefinitionInfo | None,
        caller_id: str,
    ) -> list[ProjectTarget]:
        """Resolve calls in one function and return project targets to keep walking."""
        analysis = self._analysis(target.source_file)
        if analysis is None:
            return []
        source = read_text(self.repo / target.source_file) or ""
        line_end = definition.line_end if definition else target.line
        qname = definition.qualified_name if definition else target.qualified_name
        children: list[ProjectTarget] = []
        for call in analysis.calls:
            in_body = call.caller_qualified_name == qname or target.line <= call.line <= line_end
            if not in_body:
                continue
            resolved = self.resolver.resolve_call(target.source_file, call, source)
            names = argument_names(source, call.line, call.callee_text)
            if resolved.expandable and resolved.callee_qualified_name and resolved.source_file and resolved.line:
                child = self._align(resolved)
                self._link(caller_id, child, resolved, follow=True)
                children.append(child)
                continue
            self._link_leaf(caller_id, resolved)
            seen = SeenCall(
                callee_text=call.callee_text,
                expandable=False,
                argument_names=names,
                caller_file=target.source_file,
            )
            for bridge in self.bridges:
                for extra in bridge.extra_targets(seen, self.index):
                    self._link_target(caller_id, extra, bridge_name=bridge.name, is_await=call.is_await)
                    children.append(extra)
        return children

    def _stored_children(self, node_id: str) -> list[ProjectTarget]:
        """Children recorded on a previous trace of an unchanged function."""
        children: list[ProjectTarget] = []
        for edge in self.graph.edges_from(node_id):
            if not edge.metadata.get("follow"):
                continue
            qname = edge.metadata.get("qualified_name")
            source_file = edge.metadata.get("source_file")
            line = edge.metadata.get("line")
            if qname and source_file and line:
                children.append(ProjectTarget(qname, source_file, int(line)))
        return children

    def _align(self, resolved: ResolvedCall) -> ProjectTarget:
        """Prefer the AST qualified name at the resolved line."""
        assert resolved.callee_qualified_name and resolved.source_file and resolved.line
        definition = self._definition(
            ProjectTarget(resolved.callee_qualified_name, resolved.source_file, resolved.line)
        )
        if definition:
            return ProjectTarget(definition.qualified_name, resolved.source_file, definition.line_start)
        return ProjectTarget(resolved.callee_qualified_name, resolved.source_file, resolved.line)

    def _link(self, caller_id: str, child: ProjectTarget, resolved: ResolvedCall, *, follow: bool) -> None:
        """Add a call edge into a project function."""
        definition = self._definition(child)
        self._ensure_node(child, definition)
        edge_type = EdgeType.AWAITS if resolved.is_await else EdgeType.CALLS
        self._add_edge(
            Edge(
                from_node=caller_id,
                to_node=_node_id(child, definition),
                type=edge_type,
                metadata={
                    "follow": follow,
                    "qualified_name": child.qualified_name,
                    "source_file": child.source_file,
                    "line": child.line,
                    "callee_text": resolved.callee_text,
                },
            )
        )

    def _link_target(self, caller_id: str, child: ProjectTarget, *, bridge_name: str, is_await: bool) -> None:
        """Add an edge invented by a library bridge."""
        definition = self._definition(child)
        self._ensure_node(child, definition)
        self._add_edge(
            Edge(
                from_node=caller_id,
                to_node=_node_id(child, definition),
                type=EdgeType.AWAITS if is_await else EdgeType.CALLS,
                metadata={
                    "follow": True,
                    "bridge": bridge_name,
                    "qualified_name": child.qualified_name,
                    "source_file": child.source_file,
                    "line": child.line,
                },
            )
        )

    def _link_leaf(self, caller_id: str, resolved: ResolvedCall) -> None:
        """Record a call that stops at a library or an unresolved name."""
        label = resolved.callee_qualified_name or resolved.callee_text
        node_id = make_node_id(f"lib:{label}")
        if not self.graph.get_node(node_id):
            self.graph.add_node(
                Node(
                    id=node_id,
                    type=NodeType.UNKNOWN,
                    name=label.rsplit(".", 1)[-1],
                    qualified_name=label,
                    metadata={"library": True},
                )
            )
        self._add_edge(
            Edge(
                from_node=caller_id,
                to_node=node_id,
                type=EdgeType.DEPENDS_ON,
                metadata={"callee_text": resolved.callee_text, "follow": False},
            )
        )

    def _ensure_node(self, target: ProjectTarget, definition: DefinitionInfo | None) -> None:
        """Create the function or method node."""
        name = target.qualified_name.rsplit(".", 1)[-1]
        kind = definition.kind if definition else "function"
        node_type = NodeType.METHOD if kind == "method" else NodeType.FUNCTION
        self.graph.add_node(
            Node(
                id=_node_id(target, definition),
                type=node_type,
                name=name,
                qualified_name=definition.qualified_name if definition else target.qualified_name,
                source_file=target.source_file,
                line_start=definition.line_start if definition else target.line,
                line_end=definition.line_end if definition else target.line,
                metadata={"decorators": definition.decorators if definition else []},
            )
        )

    def _definition(self, target: ProjectTarget) -> DefinitionInfo | None:
        """AST definition for a target, by qualified name or by line."""
        analysis = self._analysis(target.source_file)
        if analysis is None:
            return None
        for defn in analysis.definitions:
            if defn.qualified_name == target.qualified_name and defn.kind in ("function", "method"):
                return defn
        for defn in analysis.definitions:
            if defn.kind in ("function", "method") and defn.line_start == target.line:
                return defn
        return None

    def _analysis(self, source_file: str):
        """Parse a file once per trace."""
        if source_file in self._analyses:
            return self._analyses[source_file]
        path = self.repo / source_file
        source = read_text(path)
        if source is None or not path.exists():
            self._analyses[source_file] = None
            return None
        analysis = analyze_file(source_file, source, parse_source(source))
        self._analyses[source_file] = analysis
        return analysis

    def _add_edge(self, edge: Edge) -> None:
        """Add an edge once per origin, destination, and type."""
        for existing in self.graph.edges:
            if (
                existing.from_node == edge.from_node
                and existing.to_node == edge.to_node
                and existing.type == edge.type
            ):
                return
        self.graph.add_edge(edge)


def _node_id(target: ProjectTarget, definition: DefinitionInfo | None) -> str:
    """Stable id from the definition line when the AST has one."""
    line = definition.line_start if definition else target.line
    qname = definition.qualified_name if definition else target.qualified_name
    return make_node_id(qname, target.source_file, line)


def locate_entry(repo: Path, file: str | None, line: int | None, qualified_name: str | None) -> ProjectTarget:
    """Resolve a file:line or qualified name to a function."""
    if file and line:
        rel = file.replace("\\", "/")
        source = read_text(repo / rel)
        if source is None:
            raise FileNotFoundError(rel)
        analysis = analyze_file(rel, source, parse_source(source))
        matches = [
            defn
            for defn in analysis.definitions
            if defn.kind in ("function", "method") and defn.line_start <= line <= defn.line_end
        ]
        if not matches:
            raise LookupError(f"No function at {rel}:{line}")
        defn = sorted(matches, key=lambda item: item.line_end - item.line_start)[0]
        return ProjectTarget(defn.qualified_name, rel, defn.line_start)
    if not qualified_name:
        raise LookupError("Entry needs file:line or a qualified name")
    index = build_index(repo)
    found = index.by_qualified_name.get(qualified_name)
    if found:
        return found
    suffix = f".{qualified_name}" if "." not in qualified_name else qualified_name
    hits = [item for name, item in index.by_qualified_name.items() if name == qualified_name or name.endswith(suffix)]
    if len(hits) == 1:
        return hits[0]
    raise LookupError(f"Definition not found: {qualified_name}")
