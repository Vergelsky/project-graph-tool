"""Users stay apart, and a saved token cannot be read back."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from project_map.accounts import CabinetStore
from project_map.browse import read_file, safe_repo_path, sync_tree
from project_map.cabinet import _handler
from project_map.secrets import decrypt, encrypt
from project_map.source import git_partial_clone_command


class Client:
    """HTTP client that keeps the session cookie."""

    def __init__(self, base: str) -> None:
        self.base = base
        self.cookie: str | None = None

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        """Send one JSON request."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.cookie:
            request.add_header("Cookie", f"session={self.cookie}")
        try:
            with urllib.request.urlopen(request) as response:
                self._take_cookie(response)
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._take_cookie(exc)
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _take_cookie(self, response) -> None:
        """Remember a new session."""
        header = response.headers.get("Set-Cookie") or ""
        if "session=" not in header:
            return
        self.cookie = header.split("session=", 1)[1].split(";", 1)[0]


def test_saved_token_is_not_returned_and_other_user_cannot_open_project(tmp_path: Path) -> None:
    """The owner can use the token. Another account gets the same answer as for a missing project."""
    store = CabinetStore(tmp_path)
    owner = store.register("alice", "password1")
    other = store.register("bob", "password2")
    secret = "git-token-not-for-the-browser"
    project = store.create_project(owner["id"], "Demo", "https://example.com/repo.git", secret)
    assert secret not in json.dumps(project)
    assert project["has_token"] is True
    job_text = (store.job_dir(project["id"]) / "job.json").read_text(encoding="utf-8")
    assert secret not in job_text
    assert store.token_for(owner["id"], project["id"]) == secret
    kept = store.update_project(owner["id"], project["id"], token="")
    assert kept["has_token"] is True
    assert store.token_for(owner["id"], project["id"]) == secret
    replaced = store.update_project(owner["id"], project["id"], token="next-token-value")
    assert "next-token-value" not in json.dumps(replaced)
    assert store.token_for(owner["id"], project["id"]) == "next-token-value"
    with pytest.raises(LookupError):
        store.get_project(other["id"], project["id"])
    with pytest.raises(LookupError):
        store.token_for(other["id"], project["id"])


def test_encrypt_roundtrip_does_not_keep_the_token_in_clear_text() -> None:
    """The stored blob is not the token itself."""
    key = b"k" * 32
    blob = encrypt(key, "s3cret-value")
    assert "s3cret-value" not in blob
    assert decrypt(key, blob) == "s3cret-value"


def test_repo_path_rejects_parent_segments() -> None:
    """A file request cannot leave the repository."""
    assert safe_repo_path("app/views.py") == "app/views.py"
    with pytest.raises(ValueError):
        safe_repo_path("../secret.txt")


def test_partial_clone_lists_files_before_their_bodies_are_checked_out(tmp_path: Path) -> None:
    """The tree is available while the chosen file is still fetched one at a time."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    origin = tmp_path / "origin"
    origin.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
    )
    subprocess.run(["git", "init", str(origin)], check=True, capture_output=True, env=env)
    view = origin / "app" / "views.py"
    view.parent.mkdir()
    view.write_text("def entry():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(origin), "add", "app/views.py"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(origin), "commit", "-m", "init"], check=True, capture_output=True, env=env)
    job = tmp_path / "job"
    job.mkdir()
    files = sync_tree(job, str(origin), None)
    assert "app/views.py" in files
    checkout_file = job / "checkout" / "app" / "views.py"
    assert not checkout_file.exists()
    assert "def entry" in read_file(job, "app/views.py", None)
    assert not checkout_file.exists()


def test_partial_clone_command_keeps_the_token_out_of_the_url() -> None:
    """The header carries the token. The clone URL stays clean."""
    command = git_partial_clone_command("https://example.com/repo.git", Path("checkout"), "s3cret")
    assert command[-2] == "https://example.com/repo.git"
    assert "s3cret" not in command[-2]
    assert any("s3cret" in part for part in command)


def test_http_cabinet_hides_projects_and_tokens(tmp_path: Path) -> None:
    """Two browsers see two accounts. The token never comes back in JSON."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(CabinetStore(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        alice = Client(base)
        bob = Client(base)
        status, _alice = alice.request("POST", "/api/register", {"username": "alice", "password": "password1"})
        assert status == 201
        status, _bob = bob.request("POST", "/api/register", {"username": "bob", "password": "password2"})
        assert status == 201
        secret = "browser-must-not-see-this"
        status, project = alice.request(
            "POST",
            "/api/projects",
            {"name": "Demo", "url": "https://example.com/repo.git", "token": secret},
        )
        assert status == 201
        assert secret not in json.dumps(project)
        status, denied = bob.request("GET", f"/api/projects/{project['id']}")
        assert status == 404
        assert secret not in json.dumps(denied)
        status, listed = bob.request("GET", "/api/projects")
        assert listed["projects"] == []
        status, saved = alice.request(
            "PUT",
            f"/api/projects/{project['id']}/entry",
            {"entry": "app/views.py:42"},
        )
        assert status == 200
        assert saved["entries"] == ["app/views.py:42"]
        status, stolen = bob.request(
            "PUT",
            f"/api/projects/{project['id']}/entry",
            {"entry": "app/views.py:1"},
        )
        assert status == 404
        status, missing = alice.request("GET", f"/p/{project['id']}/output/execution_graph.json")
        assert status == 404
        assert missing["error"] == "Карта ещё не построена"
        status, hidden = bob.request("GET", f"/p/{project['id']}/output/execution_graph.json")
        assert hidden["error"] == "Проект не найден"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
