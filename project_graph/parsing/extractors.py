"""Extract definitions and calls from AST."""

from __future__ import annotations

from dataclasses import dataclass, field

from tree_sitter import Node as TSNode, Tree

from project_graph.parsing.tree_sitter_parser import node_text


@dataclass
class DefinitionInfo:
    kind: str
    name: str
    qualified_name: str
    line_start: int
    line_end: int
    decorators: list[str] = field(default_factory=list)


@dataclass
class CallInfo:
    caller_qualified_name: str
    callee_text: str
    line: int
    column: int
    is_await: bool = False


@dataclass
class FileAnalysis:
    source_file: str
    module: str
    definitions: list[DefinitionInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)


def analyze_file(source_file: str, source: str, tree: Tree) -> FileAnalysis:
    """Extract definitions and calls from a parsed file."""
    module = _path_to_module(source_file)
    analysis = FileAnalysis(source_file=source_file, module=module)
    class_stack: list[str] = []

    def visit(node: TSNode) -> None:
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                class_name = node_text(source, name_node)
                class_stack.append(class_name)
                qname = f"{module}.{'.'.join(class_stack)}"
                analysis.definitions.append(
                    DefinitionInfo(
                        kind="class",
                        name=class_name,
                        qualified_name=qname,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        decorators=_extract_decorators(source, node),
                    )
                )
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        visit(child)
                class_stack.pop()
                return
        if node.type == "decorated_definition":
            decorators = _extract_decorators(source, node)
            for child in node.children:
                if child.type in ("function_definition", "async_function_definition"):
                    _process_function(child, decorators)
            return
        if node.type in ("function_definition", "async_function_definition"):
            _process_function(node, _extract_decorators(source, node))
            return
        for child in node.children:
            visit(child)

    def _process_function(node: TSNode, decorators: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        func_name = node_text(source, name_node)
        qname = f"{module}.{'.'.join(class_stack + [func_name]) if class_stack else func_name}"
        kind = "method" if class_stack else "function"
        analysis.definitions.append(
            DefinitionInfo(
                kind=kind,
                name=func_name,
                qualified_name=qname,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                decorators=decorators,
            )
        )
        body = node.child_by_field_name("body")
        if body:
            _extract_calls_from_body(source, body, qname, analysis)

    visit(tree.root_node)
    return analysis


def _extract_decorators(source: str, node: TSNode) -> list[str]:
    """Extract decorator names from a decorated node."""
    decorators: list[str] = []
    for child in node.children:
        if child.type == "decorator":
            decorators.append(node_text(source, child).lstrip("@").split("(")[0].strip())
    return decorators


def _extract_calls_from_body(source: str, body: TSNode, caller_qname: str, analysis: FileAnalysis) -> None:
    """Walk function body and collect call expressions."""
    pending_await = False

    def walk(node: TSNode) -> None:
        nonlocal pending_await
        if node.type == "await":
            pending_await = True
            for child in node.children:
                walk(child)
            pending_await = False
            return
        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node:
                callee = node_text(source, func_node)
                line = node.start_point[0] + 1
                column = node.start_point[1]
                analysis.calls.append(
                    CallInfo(
                        caller_qualified_name=caller_qname,
                        callee_text=callee,
                        line=line,
                        column=column,
                        is_await=pending_await,
                    )
                )
        for child in node.children:
            walk(child)

    for child in body.children:
        walk(child)


def _path_to_module(source_file: str) -> str:
    """Convert relative file path to module name."""
    path = source_file.replace("\\", "/")
    if path.endswith(".py"):
        path = path[:-3]
    if path.endswith("/__init__"):
        path = path[:-9]
    return path.replace("/", ".")
