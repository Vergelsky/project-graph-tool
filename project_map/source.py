"""Materialize a job source. Git tokens stay in the environment."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def ensure_checkout(job: dict, job_dir: Path, *, token: str | None = None) -> Path:
    """Return the directory that contains the Python sources."""
    source = job["source"]
    if source.get("kind") == "local":
        path = Path(source["path"])
        if not path.is_dir():
            raise FileNotFoundError(path)
        return path
    if source.get("kind") != "git":
        raise ValueError(f"Unknown source kind: {source.get('kind')}")
    dest = job_dir / "checkout"
    if token is None:
        token = os.environ.get(job.get("token_env") or "PROJECT_MAP_GIT_TOKEN") or None
    url = source["url"]
    if (dest / ".git").exists():
        run_git(git_pull_command(dest, token), token)
        return dest
    if dest.exists():
        raise RuntimeError(f"Checkout exists and is not a git repository: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(git_clone_command(url, dest, token), token)
    return dest


def git_clone_command(url: str, dest: Path, token: str | None) -> list[str]:
    """Build a clone command. The token is an http header, not part of the URL."""
    if token:
        return ["git", "-c", _auth_header(token), "clone", "--depth", "1", url, str(dest)]
    return ["git", "clone", "--depth", "1", url, str(dest)]


def git_pull_command(dest: Path, token: str | None) -> list[str]:
    """Build a pull command for an existing checkout."""
    command = ["git", "-C", str(dest), "pull", "--ff-only"]
    if token:
        command = ["git", "-c", _auth_header(token), "-C", str(dest), "pull", "--ff-only"]
    return command


def git_partial_clone_command(url: str, dest: Path, token: str | None) -> list[str]:
    """Clone trees without file contents and without a worktree checkout."""
    command = ["git"]
    if token:
        command.extend(["-c", _auth_header(token)])
    command.extend(["clone", "--filter=blob:none", "--depth", "1", "--no-checkout", "--no-local", url, str(dest)])
    return command


def git_ls_tree_command(dest: Path) -> list[str]:
    """List files already recorded in the cloned commit."""
    return ["git", "-C", str(dest), "ls-tree", "-r", "-z", "--name-only", "HEAD"]


def git_show_command(dest: Path, path: str, token: str | None) -> list[str]:
    """Read one file. A partial clone fetches that blob on demand."""
    command = ["git"]
    if token:
        command.extend(["-c", _auth_header(token)])
    command.extend(["-C", str(dest), "show", f"HEAD:{path}"])
    return command


def git_checkout_command(dest: Path, token: str | None) -> list[str]:
    """Download the worktree when a trace needs the sources on disk."""
    command = ["git"]
    if token:
        command.extend(["-c", _auth_header(token)])
    command.extend(["-C", str(dest), "checkout", "--force", "HEAD"])
    return command


def run_git(command: list[str], token: str | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run git and raise a message that does not contain the token."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    completed = subprocess.run(command, capture_output=True, env=env)
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        if token:
            detail = detail.replace(token, "*****")
        raise RuntimeError(detail or "Команда git завершилась с ошибкой")
    return completed


def _auth_header(token: str) -> str:
    """Git config line passed via -c so the token is not written into .git/config."""
    return f"http.extraheader=AUTHORIZATION: bearer {token}"
