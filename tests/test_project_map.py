"""Tests for the job-based execution map."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from project_map.models import NodeType
from project_map.analyze.projection import project
from project_map.analyze.resolver import JediResolver
from project_map.describe import describe_job
from project_map.job import add_entry, create_job, load_graph, trace_job
from project_map.libraries.base import ProjectTarget, SeenCall
from project_map.serve import _handler, view_payload
from project_map.source import git_clone_command


class FakeClient:
    """Records prompts and returns a fixed card text."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        """Return a stable description."""
        self.prompts.append(prompt)
        return "Карточка"


class FakeBridge:
    """Test double: external() continues at the project function named target."""

    name = "fake"

    def extra_targets(self, call: SeenCall, index) -> list[ProjectTarget]:
        """Return target when the callee is external."""
        if call.callee_text != "external":
            return []
        return index.named("target")[:1]


class CountingResolver:
    """Counts which functions asked Jedi to resolve their calls."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.callers: list[str] = []

    def resolve_call(self, source_file: str, call, source: str):
        """Delegate and record the caller."""
        self.callers.append(call.caller_qualified_name)
        return self.inner.resolve_call(source_file, call, source)


def _write(path: Path, text: str) -> None:
    """Write a source file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_chain_is_not_cut_at_fifteen_layers(tmp_path: Path) -> None:
    """Sixteen project calls stay on the map. The library call does not."""
    lines = ["import json", ""]
    for index in range(16):
        if index < 15:
            lines.append(f"def f{index}():\n    return f{index + 1}()\n")
        else:
            lines.append('def f15():\n    return json.loads("{}")\n')
    _write(tmp_path / "chain.py", "\n".join(lines))
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["chain.py:3"])
    trace_job(job)
    graph = load_graph(job)
    names = {node.qualified_name for node in graph.nodes}
    assert "chain.f15" in names
    assert all("site-packages" not in (node.source_file or "") for node in graph.nodes)
    assert any(node.metadata.get("library") for node in graph.nodes)


def test_fake_bridge_reenters_project_code(tmp_path: Path) -> None:
    """A library module can add an edge without a change to the tracer."""
    _write(
        tmp_path / "app.py",
        "def entry():\n    external()\n\ndef target():\n    return 1\n",
    )
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["app.py:1"])
    trace_job(job, bridges=[FakeBridge()])
    names = {node.qualified_name for node in load_graph(job).nodes}
    assert "app.target" in names


def test_callback_bridge_follows_a_passed_function(tmp_path: Path) -> None:
    """json.dumps(target) keeps walking target and stops inside json."""
    _write(
        tmp_path / "app.py",
        "import json\n\ndef entry():\n    return json.dumps(target)\n\ndef target():\n    return 1\n",
    )
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["app.py:3"])
    trace_job(job)
    names = {node.qualified_name for node in load_graph(job).nodes}
    assert "app.target" in names


def test_second_entry_does_not_reresolve_unchanged_file(tmp_path: Path) -> None:
    """A new entry reuses functions whose file hash did not change."""
    _write(
        tmp_path / "a.py",
        "def entry_a():\n    return shared()\n\ndef shared():\n    return 1\n",
    )
    _write(
        tmp_path / "b.py",
        "def entry_b():\n    return other()\n\ndef other():\n    return 2\n",
    )
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["a.py:1"])
    trace_job(job)
    counter = CountingResolver(JediResolver(tmp_path))
    add_entry(job, "b.py:1")
    trace_job(job, resolver=counter)
    assert not any(caller.endswith("shared") for caller in counter.callers)
    assert any(caller.endswith("entry_b") for caller in counter.callers)
    names = {node.qualified_name for node in load_graph(job).nodes}
    assert "a.shared" in names
    assert "b.other" in names


def test_descriptions_survive_trace_and_keep_level(tmp_path: Path) -> None:
    """describe writes level=function beside the graph and a second pass skips fresh cards."""
    _write(tmp_path / "app.py", "def entry():\n    return 1\n")
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["app.py:1"])
    trace_job(job)
    client = FakeClient()
    assert describe_job(job, client, level="function") == 1
    stored = json.loads((job / "descriptions.json").read_text(encoding="utf-8"))
    assert stored["records"][0]["level"] == "function"
    assert stored["records"][0]["text"] == "Карточка"
    graph_text = (job / "execution_graph.json").read_text(encoding="utf-8")
    assert "Карточка" not in graph_text
    assert describe_job(job, client, level="function") == 0
    trace_job(job)
    assert "Карточка" in (job / "descriptions.json").read_text(encoding="utf-8")
    _write(tmp_path / "app.py", "def entry():\n    return 2\n")
    trace_job(job)
    assert describe_job(job, client, level="function") == 1
    assert describe_job(job, client, level="file") >= 1
    stored = json.loads((job / "descriptions.json").read_text(encoding="utf-8"))
    levels = {item["level"] for item in stored["records"]}
    assert levels == {"function", "file"}
    file_prompts = [prompt for prompt in client.prompts if "Тип: FILE" in prompt and "app.entry" in prompt]
    assert file_prompts
    assert "Карточка" not in file_prompts[-1]
    payload = view_payload(job)
    assert payload["meta"]["level"] == "function"
    assert any(node.get("description") == "Карточка" for node in payload["nodes"])


def test_file_projection_collapses_calls_inside_one_file(tmp_path: Path) -> None:
    """File level keeps cross-file edges and drops calls inside a file."""
    _write(tmp_path / "a.py", "def entry():\n    return local()\n\ndef local():\n    return 1\n")
    _write(tmp_path / "b.py", "from a import entry\n\ndef run():\n    return entry()\n")
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["b.py:3"])
    trace_job(job)
    collapsed = project(load_graph(job), "file")
    files = {node.name for node in collapsed.nodes if node.type == NodeType.FILE}
    assert "a.py" in files
    assert "b.py" in files
    internal = [
        edge
        for edge in collapsed.edges
        if edge.from_node == edge.to_node
    ]
    assert not internal


def test_git_token_stays_out_of_the_url_and_job(tmp_path: Path) -> None:
    """The clone command carries the token as a header. job.json never stores it."""
    command = git_clone_command("https://example.com/repo.git", Path("checkout"), "s3cret")
    url = command[command.index("clone") + 3]
    assert url == "https://example.com/repo.git"
    assert "s3cret" not in url
    assert any("s3cret" in part for part in command)
    job = tmp_path / "job"
    create_job(job, "https://example.com/repo.git", ["app.py:1"])
    stored = (job / "job.json").read_text(encoding="utf-8")
    assert "s3cret" not in stored
    assert json.loads(stored)["token_env"] == "PROJECT_MAP_GIT_TOKEN"


def test_viewer_endpoint_returns_projected_graph(tmp_path: Path) -> None:
    """The viewer URL is the function projection, not the raw cache."""
    _write(tmp_path / "app.py", "def entry():\n    return 1\n")
    job = tmp_path / "job"
    create_job(job, str(tmp_path), ["app.py:1"])
    trace_job(job)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(job))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/output/execution_graph.json") as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert payload["meta"]["level"] == "function"
    assert any(node["type"] == "ENTRY_POINT" for node in payload["nodes"])
