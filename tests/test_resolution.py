"""Jedi still resolves a project method and stops on the standard library."""

from __future__ import annotations

import shutil
from pathlib import Path

import jedi

from project_map.analyze.definitions import resolve_call_site
from project_map.analyze.resolver import JediResolver
from project_map.job import create_job, load_graph, trace_job
from project_map.parse.extract import analyze_file
from project_map.parse.tree import parse_source

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "resolution_project"


def _copy(tmp_path: Path) -> Path:
    """Copy the fixture into a temporary repository."""
    shutil.copytree(FIXTURE_ROOT, tmp_path, dirs_exist_ok=True)
    return tmp_path


def test_resolve_imported_class_method(tmp_path: Path) -> None:
    """Service.run in the view lands on the method in services.py."""
    repo = _copy(tmp_path)
    source = (repo / "app/views.py").read_text(encoding="utf-8")
    analysis = analyze_file("app/views.py", source, parse_source(source))
    call = next(item for item in analysis.calls if item.callee_text == "Service.run")
    script = jedi.Script(source, path=str(repo / "app/views.py"), project=jedi.Project(path=str(repo)))
    resolved = resolve_call_site(script, call, repo, source=source)
    assert resolved is not None
    assert resolved.source_file == "app/services.py"
    assert resolved.qualified_name.endswith("Service.run")
    assert resolved.expandable is True


def test_library_call_is_not_expandable(tmp_path: Path) -> None:
    """json.loads stays outside the project."""
    repo = _copy(tmp_path)
    source = (repo / "app/views.py").read_text(encoding="utf-8")
    analysis = analyze_file("app/views.py", source, parse_source(source))
    call = next(item for item in analysis.calls if item.callee_text == "json.loads")
    resolved = JediResolver(repo).resolve_call("app/views.py", call, source)
    assert resolved.expandable is False


def test_trace_crosses_modules(tmp_path: Path) -> None:
    """The walk from the view reaches the helper in another file."""
    repo = _copy(tmp_path / "repo")
    job = tmp_path / "job"
    create_job(job, str(repo), ["app/views.py:6"])
    trace_job(job)
    names = {node.qualified_name for node in load_graph(job).nodes}
    assert "app.services.Service.run" in names
    assert "app.helpers.Helper.work" in names
    assert "app.helpers.deep_transform" in names
