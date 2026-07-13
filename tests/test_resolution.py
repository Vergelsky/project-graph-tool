"""Tests for Jedi call resolution pipeline."""

from __future__ import annotations

import shutil
from pathlib import Path

import jedi
import pytest

from project_graph.config import init_workspace
from project_graph.parsing.ast_store import ASTStore
from project_graph.parsing.extractors import CallInfo
from project_graph.resolution.definition_resolver import resolve_call_site
from project_graph.resolution.incremental_call_graph import IncrementalCallGraphBuilder
from project_graph.resolution.jedi_resolver import JediResolver
from project_graph.trace_roots.models import TracePointer, TraceRoot
from project_graph.trace_roots.resolver import RootResolver

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "resolution_project"


@pytest.fixture
def resolution_workspace(tmp_path: Path):
    """Copy resolution_project fixture into an isolated workspace."""
    shutil.copytree(FIXTURE_ROOT, tmp_path, dirs_exist_ok=True)
    init_workspace(tmp_path)
    yield tmp_path


def test_callinfo_has_callee_column(resolution_workspace: Path) -> None:
    """AST extraction stores callee_column for call expressions."""
    analysis = ASTStore().get_file("app/views.py")
    assert analysis is not None
    service_calls = [c for c in analysis.calls if "Service.run" in c.callee_text]
    assert service_calls
    call = service_calls[0]
    assert call.callee_column <= call.column


def test_resolve_imported_class_method(resolution_workspace: Path) -> None:
    """Imported Class.method resolves to the definition module."""
    repo_root = resolution_workspace
    source = (repo_root / "app/views.py").read_text(encoding="utf-8")
    analysis = ASTStore().get_file("app/views.py")
    assert analysis is not None
    call = next(c for c in analysis.calls if c.callee_text == "Service.run")
    script = jedi.Script(source, path=str(repo_root / "app/views.py"), project=jedi.Project(path=str(repo_root)))
    resolved = resolve_call_site(script, call, repo_root, source=source)
    assert resolved is not None
    assert resolved.source_file == "app/services.py"
    assert resolved.qualified_name.endswith("Service.run")
    assert resolved.expandable is True


def test_follow_imports_not_import_line(resolution_workspace: Path) -> None:
    """Callee definition is not the import line in the caller file."""
    resolver = JediResolver()
    analysis = ASTStore().get_file("app/views.py")
    assert analysis is not None
    call = next(c for c in analysis.calls if c.callee_text == "Service.run")
    resolved = resolver.resolve_call("app/views.py", call)
    assert resolved.resolved is True
    assert resolved.source_file == "app/services.py"
    assert resolved.line != 4


def test_unresolved_external(resolution_workspace: Path) -> None:
    """stdlib calls are not expandable project definitions."""
    resolver = JediResolver()
    analysis = ASTStore().get_file("app/views.py")
    assert analysis is not None
    call = next(c for c in analysis.calls if c.callee_text == "json.loads")
    resolved = resolver.resolve_call("app/views.py", call)
    assert resolved.resolved is False
    assert resolved.expandable is False


def test_incremental_bfs_depth(resolution_workspace: Path) -> None:
    """BFS from view endpoint reaches helpers.deep_transform."""
    builder = IncrementalCallGraphBuilder()
    root_resolver = RootResolver(builder.graph)
    resolved = root_resolver.resolve(
        TraceRoot(id="endpoint", pointer=TracePointer(kind="def", file="app/views.py", line=7))
    )
    builder.expand_from(resolved)
    qnames = {node.qualified_name for node in builder.graph.nodes}
    assert "app.helpers.Helper.work" in qnames
    assert "app.helpers.deep_transform" in qnames
    assert any(node.source_file == "app/services.py" for node in builder.graph.nodes)
