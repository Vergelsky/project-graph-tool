"""Pull identifier arguments out of a call expression."""

from __future__ import annotations

from project_map.parse.tree import node_text, parse_source


def argument_names(source: str, line: int, callee_text: str) -> list[str]:
    """Return identifier arguments of the call on this line."""
    tree = parse_source(source)
    found: list[str] = []

    def walk(node) -> None:
        if node.type == "call" and node.start_point[0] + 1 == line:
            func = node.child_by_field_name("function")
            if func is not None and node_text(source, func) == callee_text:
                args = node.child_by_field_name("arguments")
                if args is not None:
                    found.extend(_identifiers(source, args))
                return
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return found


def _identifiers(source: str, node) -> list[str]:
    """Identifier texts used as positional or keyword values."""
    names: list[str] = []
    for child in node.children:
        if child.type == "identifier":
            names.append(node_text(source, child))
        elif child.type == "keyword_argument":
            value = child.child_by_field_name("value")
            if value is not None and value.type == "identifier":
                names.append(node_text(source, value))
    return names
