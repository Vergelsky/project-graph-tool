"""Keep pytest's Windows temp-link cleanup from failing a green run."""

from __future__ import annotations

import _pytest.pathlib as pytest_pathlib

_cleanup_dead_symlinks = pytest_pathlib.cleanup_dead_symlinks


def _cleanup_dead_symlinks_quietly(root):
    """Ignore a locked pytest-current symlink. The tests themselves already finished."""
    try:
        _cleanup_dead_symlinks(root)
    except PermissionError:
        return


pytest_pathlib.cleanup_dead_symlinks = _cleanup_dead_symlinks_quietly
