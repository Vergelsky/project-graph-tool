"""Parse Python source files with tree-sitter."""

from __future__ import annotations

import tree_sitter_python as tspython
from tree_sitter import Language, Node as TSNode, Parser, Tree

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


def parse_source(source: str) -> Tree:
    """Parse Python source into a tree-sitter tree."""
    return _parser.parse(source.encode("utf-8"))


def node_text(source: str, node: TSNode) -> str:
    """Extract text for a tree-sitter node."""
    return source.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8")
