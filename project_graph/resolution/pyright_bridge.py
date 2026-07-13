"""Optional Pyright bridge for unresolved calls."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from project_graph.config import TOOL_ROOT


def pyright_available() -> bool:
    """Check if pyright CLI is installed."""
    return shutil.which("pyright") is not None


def run_pyright_check() -> dict | None:
    """Run pyright --outputjson on the project."""
    if not pyright_available():
        return None
    try:
        result = subprocess.run(
            ["pyright", "--outputjson"],
            cwd=str(TOOL_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None
    return None


def get_type_info_for_symbol(file_path: str, line: int, column: int) -> str | None:
    """Get type info via pyright if available."""
    output = run_pyright_check()
    if not output:
        return None
    for diag in output.get("generalDiagnostics", []):
        if diag.get("file") == file_path and diag.get("range", {}).get("start", {}).get("line") == line - 1:
            return diag.get("message")
    return None
