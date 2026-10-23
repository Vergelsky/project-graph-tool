"""Users, sessions, and projects. A project is visible only to its owner."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from project_map.job import create_job, load_job, set_entries, update_source
from project_map.secrets import decrypt, encrypt, load_or_create_key

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PASSWORD_ITERATIONS = 200_000
SESSION_SECONDS = 14 * 24 * 3600


class CabinetStore:
    """SQLite cabinet. Tokens are encrypted and are not part of the public project record."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs = root / "jobs"
        self.jobs.mkdir(parents=True, exist_ok=True)
        self._key = load_or_create_key(root / "secret.key")
        self._db_path = root / "cabinet.sqlite"
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    token_cipher TEXT,
                    created_at INTEGER NOT NULL
                );
                """
            )

    def register(self, username: str, password: str) -> dict:
        """Create an account. The name must be free."""
        username = _username(username)
        _password(password)
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
        user_id = secrets.token_hex(8)
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (id, username, password_salt, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, salt.hex(), digest.hex(), int(time.time())),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Такое имя уже занято") from exc
        return {"id": user_id, "username": username}

    def open_session(self, username: str, password: str) -> str:
        """Return a new session id, or reject the login."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        if row is None or not _password_matches(password, row["password_salt"], row["password_hash"]):
            raise PermissionError("Неверное имя или пароль")
        raw = secrets.token_urlsafe(32)
        expires = int(time.time()) + SESSION_SECONDS
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (_session_hash(raw), row["id"], expires),
            )
        return raw

    def close_session(self, raw: str) -> None:
        """Drop one session."""
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_session_hash(raw),))

    def user_for_session(self, raw: str | None) -> dict | None:
        """Return the account for a cookie, when the session is still valid."""
        if not raw:
            return None
        now = int(time.time())
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT users.id, users.username, sessions.expires_at
                FROM sessions JOIN users ON users.id = sessions.user_id
                WHERE sessions.token_hash = ?
                """,
                (_session_hash(raw),),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] < now:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_session_hash(raw),))
                return None
        return {"id": row["id"], "username": row["username"]}

    def create_project(self, owner_id: str, name: str, url: str, token: str) -> dict:
        """Save a project. The token is encrypted and is not returned."""
        name = _name(name)
        url = _url(url)
        token = token.strip()
        project_id = secrets.token_hex(8)
        cipher = encrypt(self._key, token) if token else None
        job_dir = self.job_dir(project_id)
        create_job(job_dir, url, [], job_id=project_id)
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO projects (id, owner_id, name, url, token_cipher, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, owner_id, name, url, cipher, int(time.time())),
                )
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
        return self.get_project(owner_id, project_id)

    def list_projects(self, owner_id: str) -> list[dict]:
        """Projects of one user."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE owner_id = ? ORDER BY created_at",
                (owner_id,),
            ).fetchall()
        return [self._public(row) for row in rows]

    def get_project(self, owner_id: str, project_id: str) -> dict:
        """One owned project. Another user's id is the same as a missing id."""
        return self._public(self._owned(owner_id, project_id))

    def update_project(
        self,
        owner_id: str,
        project_id: str,
        *,
        name: str | None = None,
        url: str | None = None,
        token: str | None = None,
    ) -> dict:
        """Change name, address, or token. An empty token keeps the saved one."""
        row = self._owned(owner_id, project_id)
        next_name = _name(name) if name is not None else row["name"]
        next_url = _url(url) if url is not None else row["url"]
        cipher = row["token_cipher"]
        if token and token.strip():
            cipher = encrypt(self._key, token.strip())
        if next_url != row["url"]:
            update_source(self.job_dir(project_id), next_url)
            checkout = self.job_dir(project_id) / "checkout"
            if checkout.exists():
                shutil.rmtree(checkout)
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET name = ?, url = ?, token_cipher = ? WHERE id = ?",
                (next_name, next_url, cipher, project_id),
            )
        return self.get_project(owner_id, project_id)

    def set_entry(self, owner_id: str, project_id: str, entry: str) -> dict:
        """Store the single entry point the user picked."""
        self._owned(owner_id, project_id)
        text = entry.strip()
        if not text:
            raise ValueError("Укажите точку входа")
        set_entries(self.job_dir(project_id), [text])
        return self.get_project(owner_id, project_id)

    def token_for(self, owner_id: str, project_id: str) -> str | None:
        """Decrypt the token for a git call. Callers must not send it back to the browser."""
        row = self._owned(owner_id, project_id)
        if not row["token_cipher"]:
            return None
        return decrypt(self._key, row["token_cipher"])

    def job_dir(self, project_id: str) -> Path:
        """Job folder for a project id."""
        return self.jobs / project_id

    def _owned(self, owner_id: str, project_id: str) -> sqlite3.Row:
        """Load a row the user owns."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ? AND owner_id = ?",
                (project_id, owner_id),
            ).fetchone()
        if row is None:
            raise LookupError("Проект не найден")
        return row

    def _public(self, row: sqlite3.Row) -> dict:
        """Project fields the browser is allowed to see."""
        job_path = self.job_dir(row["id"]) / "job.json"
        entries: list[str] = []
        if job_path.exists():
            entries = [str(item.get("id") or "") for item in load_job(self.job_dir(row["id"])).get("entries") or []]
        return {
            "id": row["id"],
            "name": row["name"],
            "url": row["url"],
            "has_token": bool(row["token_cipher"]),
            "entries": entries,
        }

    @contextmanager
    def _connect(self):
        """Open the cabinet database and close it after the transaction."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _username(value: str) -> str:
    """Validate a login name."""
    text = value.strip()
    if not USERNAME_RE.fullmatch(text):
        raise ValueError("Имя: 3–32 символа, латиница, цифры, точка, _ или -")
    return text


def _password(value: str) -> None:
    """Reject a short password."""
    if len(value) < 8 or len(value) > 200:
        raise ValueError("Пароль: от 8 до 200 символов")


def _password_matches(password: str, salt_hex: str, digest_hex: str) -> bool:
    """Check a password without leaking which part failed."""
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PASSWORD_ITERATIONS)
    return hmac.compare_digest(got, bytes.fromhex(digest_hex))


def _name(value: str) -> str:
    """Validate a project title."""
    text = value.strip()
    if not text or len(text) > 80:
        raise ValueError("Название проекта: от 1 до 80 символов")
    return text


def _url(value: str) -> str:
    """Validate a repository URL."""
    text = value.strip()
    if not text.startswith(("https://", "http://")) or any(char in text for char in " \n\r"):
        raise ValueError("Нужен http или https адрес репозитория")
    return text


def _session_hash(raw: str) -> str:
    """Store the session by hash so the database does not contain the cookie."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
