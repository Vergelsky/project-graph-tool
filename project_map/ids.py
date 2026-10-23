"""Generate stable node identifiers."""

import hashlib
import re


def make_node_id(qualified_name: str, source_file: str | None = None, line: int | None = None) -> str:
    """Build a stable node id from qualified name and optional location."""
    base = qualified_name
    if source_file:
        base = f"{source_file}:{base}"
    if line is not None:
        base = f"{base}:{line}"
    slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    if len(slug) <= 120:
        return slug
    digest = hashlib.sha256(base.encode()).hexdigest()[:12]
    return f"{slug[:100]}_{digest}"
