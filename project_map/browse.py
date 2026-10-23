"""Read a private repository one file at a time."""

from __future__ import annotations

from pathlib import Path

from project_map.source import (
    git_checkout_command,
    git_ls_tree_command,
    git_partial_clone_command,
    git_show_command,
    run_git,
)

MAX_FILE_BYTES = 1_000_000


def safe_repo_path(path: str) -> str:
    """Reject paths that leave the repository."""
    text = path.replace("\\", "/").strip()
    if text.startswith("/"):
        text = text[1:]
    parts = text.split("/")
    if not text or any(part in ("", ".", "..") for part in parts):
        raise ValueError("Некорректный путь к файлу")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise ValueError("Некорректный путь к файлу")
    return text


def sync_tree(job_dir: Path, url: str, token: str | None) -> list[str]:
    """Clone commit trees if needed and return file paths. File bodies stay on the remote."""
    dest = _checkout(job_dir)
    if not (dest / ".git").is_dir():
        if dest.exists():
            raise RuntimeError(f"Каталог уже есть и это не git: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_git(git_partial_clone_command(url, dest, token), token)
    listing = run_git(git_ls_tree_command(dest), token)
    names = [item.decode("utf-8", errors="replace") for item in listing.stdout.split(b"\0") if item]
    return sorted(names)


def read_file(job_dir: Path, path: str, token: str | None) -> str:
    """Fetch one file from the remote when the local clone does not have its blob yet."""
    dest = _checkout(job_dir)
    if not (dest / ".git").is_dir():
        raise FileNotFoundError("Сначала загрузите структуру репозитория")
    safe = safe_repo_path(path)
    shown = run_git(git_show_command(dest, safe, token), token)
    if b"\x00" in shown.stdout:
        raise ValueError("Это не текстовый файл")
    if len(shown.stdout) > MAX_FILE_BYTES:
        raise ValueError("Файл слишком большой для просмотра")
    return shown.stdout.decode("utf-8", errors="replace")


def materialize_worktree(job_dir: Path, token: str | None) -> Path:
    """Put sources on disk before a trace. Browsing a file does not do this."""
    dest = _checkout(job_dir)
    if not (dest / ".git").is_dir():
        raise FileNotFoundError("Сначала загрузите структуру репозитория")
    run_git(git_checkout_command(dest, token), token)
    return dest


def _checkout(job_dir: Path) -> Path:
    """Checkout directory inside one job."""
    return job_dir / "checkout"
