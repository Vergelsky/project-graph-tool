"""Read and write trace queue and done files."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from project_graph.config import get_data_config_dir
from project_graph.trace_roots.models import TraceDoneEntry, TracePointer, TraceRoot

QUEUE_FILENAME = "trace_queue.yaml"
DONE_FILENAME = "trace_done.yaml"


class TraceStore:
    """Manage trace_queue.yaml and trace_done.yaml in data-repo."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_data_config_dir()
        self.queue_path = self.config_dir / QUEUE_FILENAME
        self.done_path = self.config_dir / DONE_FILENAME

    def load_queue(self) -> list[TraceRoot]:
        """Load roots from trace_queue.yaml."""
        return self._load_roots(self.queue_path)

    def load_done(self) -> list[TraceDoneEntry]:
        """Load processed roots from trace_done.yaml."""
        if not self.done_path.exists():
            return []
        data = yaml.safe_load(self.done_path.read_text(encoding="utf-8")) or {}
        entries: list[TraceDoneEntry] = []
        for raw in data.get("roots", []):
            entries.append(TraceDoneEntry.model_validate(raw))
        return entries

    def save_queue(self, roots: list[TraceRoot]) -> None:
        """Write trace_queue.yaml."""
        self._save_roots(self.queue_path, roots)

    def save_done(self, entries: list[TraceDoneEntry]) -> None:
        """Write trace_done.yaml."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = {"roots": [entry.model_dump(mode="json") for entry in entries]}
        self.done_path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def load_roots_file(self, path: Path) -> list[TraceRoot]:
        """Load roots from an arbitrary YAML file."""
        return self._load_roots(path)

    def append_to_queue(self, roots: list[TraceRoot]) -> None:
        """Append roots to queue without duplicates."""
        existing = self.load_queue()
        merged = existing + [root for root in roots if not self._is_duplicate(root, existing)]
        self.save_queue(merged)

    def remove_from_queue(self, root_ids: set[str]) -> None:
        """Remove processed roots from queue by id."""
        remaining = [root for root in self.load_queue() if self.ensure_id(root) not in root_ids]
        self.save_queue(remaining)

    def upsert_done(self, entry: TraceDoneEntry) -> None:
        """Add or update a done entry."""
        entries = self.load_done()
        by_id = {entry.id: entry for entry in entries}
        by_id[entry.id] = entry
        self.save_done(list(by_id.values()))

    @staticmethod
    def ensure_id(root: TraceRoot) -> str:
        """Return root id or generate one from pointer."""
        if root.id:
            return root.id
        return default_root_id(root.pointer)

    @staticmethod
    def pointer_key(pointer: TracePointer) -> str:
        """Build dedup key for a pointer."""
        if pointer.qualified_name:
            return f"{pointer.kind}:qname:{pointer.qualified_name}"
        return f"{pointer.kind}:file:{pointer.file}:{pointer.line}"

    def _load_roots(self, path: Path) -> list[TraceRoot]:
        """Load TraceRoot list from YAML."""
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [TraceRoot.model_validate(raw) for raw in data.get("roots", [])]

    def _save_roots(self, path: Path, roots: list[TraceRoot]) -> None:
        """Write TraceRoot list to YAML."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = {"roots": [root.model_dump(mode="json") for root in roots]}
        path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _is_duplicate(self, root: TraceRoot, existing: list[TraceRoot]) -> bool:
        """Check if root already exists in list."""
        key = self.pointer_key(root.pointer)
        root_id = self.ensure_id(root)
        for item in existing:
            if self.ensure_id(item) == root_id:
                return True
            if self.pointer_key(item.pointer) == key:
                return True
        return False


def default_root_id(pointer: TracePointer) -> str:
    """Generate default root id from pointer."""
    if pointer.qualified_name:
        slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", pointer.qualified_name)
        return slug[-80:] if len(slug) > 80 else slug
    file_part = (pointer.file or "unknown").replace("/", "_").replace("\\", "_")
    return f"{file_part}_{pointer.line}"


def parse_cli_pointer(kind: str, value: str) -> TracePointer:
    """Parse --def/--call CLI value into TracePointer."""
    if kind == "call":
        file_path, line = _parse_file_line(value)
        return TracePointer(kind="call", file=file_path, line=line)
    if _looks_like_file_line(value):
        file_path, line = _parse_file_line(value)
        return TracePointer(kind="def", file=file_path, line=line)
    return TracePointer(kind="def", qualified_name=value)


def _looks_like_file_line(value: str) -> bool:
    """Return True if value looks like path:line."""
    if ":" not in value:
        return False
    file_path, line_str = value.rsplit(":", 1)
    return line_str.isdigit() and (".py" in file_path or "/" in file_path or "\\" in file_path)


def _parse_file_line(value: str) -> tuple[str, int]:
    """Split path:line string."""
    file_path, line_str = value.rsplit(":", 1)
    if not line_str.isdigit():
        raise ValueError(f"Invalid file:line pointer: {value}")
    return file_path.replace("\\", "/"), int(line_str)
