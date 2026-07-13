"""Configuration paths and constants for the graph tool."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

TOOL_ROOT = Path(__file__).resolve().parent.parent

DATA_ROOT: Path | None = None
REPO_ROOT: Path | None = None
OUTPUT_DIR: Path | None = None
CACHE_DIR: Path | None = None
DATA_CONFIG_DIR: Path | None = None
TOOL_CONFIG_DIR = TOOL_ROOT / "config"

# Backward-compatible alias for tool-level YAML configs.
CONFIG_DIR = TOOL_CONFIG_DIR

WORKSPACE_FILE = "workspace.yaml"
MAX_TRACE_DEPTH = 15

EXCLUDE_DIRS = {
    "migrations",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "static",
    "bundles",
    ".git",
}

EXCLUDE_FILE_PATTERNS = ("test_", "_test.py", "conftest.py")


class WorkspaceNotConfiguredError(RuntimeError):
    """Raised when DATA_ROOT cannot be resolved."""


def _resolve_data_root(explicit: str | Path | None = None) -> Path:
    """Resolve data workspace directory from flag, env, or cwd."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_path = os.environ.get("PROJECT_GRAPH_DATA")
    if env_path:
        return Path(env_path).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / WORKSPACE_FILE).exists():
        return cwd.resolve()
    raise WorkspaceNotConfiguredError(
        "Data workspace not configured. Set PROJECT_GRAPH_DATA, pass --workspace, "
        f"or run from a directory containing {WORKSPACE_FILE}."
    )


def _load_workspace(data_root: Path) -> dict:
    """Load workspace.yaml from the data directory."""
    workspace_path = data_root / WORKSPACE_FILE
    if not workspace_path.exists():
        raise WorkspaceNotConfiguredError(f"Missing workspace file: {workspace_path}")
    data = yaml.safe_load(workspace_path.read_text(encoding="utf-8")) or {}
    if not data.get("project_path"):
        raise WorkspaceNotConfiguredError(f"workspace.yaml must define project_path: {workspace_path}")
    return data


def _resolve_repo_root(data_root: Path, workspace: dict) -> Path:
    """Resolve project source root from workspace config or env override."""
    env_repo = os.environ.get("PROJECT_GRAPH_REPO")
    if env_repo:
        repo_root = Path(env_repo).expanduser().resolve()
    else:
        repo_root = (data_root / workspace["project_path"]).resolve()
    if not repo_root.exists():
        raise WorkspaceNotConfiguredError(f"Project path does not exist: {repo_root}")
    if not ((repo_root / "manage.py").exists() or (repo_root / "pyproject.toml").exists()):
        raise WorkspaceNotConfiguredError(
            f"Project path must contain manage.py or pyproject.toml: {repo_root}"
        )
    return repo_root


def init_workspace(explicit: str | Path | None = None) -> None:
    """Initialize DATA_ROOT, REPO_ROOT, and derived paths."""
    global DATA_ROOT, REPO_ROOT, OUTPUT_DIR, CACHE_DIR, DATA_CONFIG_DIR

    data_root = _resolve_data_root(explicit)
    workspace = _load_workspace(data_root)
    repo_root = _resolve_repo_root(data_root, workspace)

    DATA_ROOT = data_root
    REPO_ROOT = repo_root
    OUTPUT_DIR = DATA_ROOT / "output"
    CACHE_DIR = OUTPUT_DIR / ".cache"
    DATA_CONFIG_DIR = DATA_ROOT / "config"


def require_workspace() -> None:
    """Ensure workspace paths are initialized."""
    if DATA_ROOT is None or REPO_ROOT is None or OUTPUT_DIR is None:
        init_workspace()


def get_repo_root() -> Path:
    """Return initialized project source root."""
    require_workspace()
    assert REPO_ROOT is not None
    return REPO_ROOT


def get_output_dir() -> Path:
    """Return initialized output directory."""
    require_workspace()
    assert OUTPUT_DIR is not None
    return OUTPUT_DIR


def get_data_config_dir() -> Path:
    """Return initialized data config directory."""
    require_workspace()
    assert DATA_CONFIG_DIR is not None
    return DATA_CONFIG_DIR


def get_cache_dir() -> Path:
    """Return initialized cache directory."""
    require_workspace()
    assert CACHE_DIR is not None
    return CACHE_DIR
