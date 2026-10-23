"""Locate Python files and hash them for incremental traces."""

from __future__ import annotations

import hashlib
from pathlib import Path

EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
    "venv",
}


def iter_python_files(repo: Path) -> list[Path]:
    """Python files under repo, skipping virtualenvs and caches."""
    files: list[Path] = []
    for path in repo.rglob("*.py"):
        if set(path.parts) & EXCLUDE_DIRS:
            continue
        files.append(path)
    return sorted(files)


def file_hashes(repo: Path) -> dict[str, str]:
    """SHA256 of each project Python file, keyed by repo-relative path."""
    hashes: dict[str, str] = {}
    for path in iter_python_files(repo):
        rel = path.relative_to(repo).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def read_text(path: Path) -> str | None:
    """Read UTF-8 source. Non-UTF-8 files are skipped."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
