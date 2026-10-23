"""Local cabinet: one account sees only its own projects."""

from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from project_map.accounts import CabinetStore
from project_map.browse import materialize_worktree, read_file, safe_repo_path, sync_tree
from project_map.job import trace_job
from project_map.serve import TOOL_ROOT, _layout_name, view_payload

CABINET_ROOT = TOOL_ROOT / "cabinet"
PROJECT_ID_RE = re.compile(r"^[0-9a-f]{16}$")
MAX_BODY = 1_048_576


def serve_cabinet(root: Path, port: int) -> None:
    """Block and serve the cabinet until interrupted."""
    store = CabinetStore(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), _handler(store))
    print(f"Cabinet at http://127.0.0.1:{port}/")
    server.serve_forever()


def _handler(store: CabinetStore) -> type[BaseHTTPRequestHandler]:
    """HTTP handler bound to one cabinet store."""

    class CabinetHandler(BaseHTTPRequestHandler):
        """Sessions, projects, lazy file reads, and the map for the owner."""

        def do_GET(self) -> None:
            """Read routes."""
            path, query = _split(self.path)
            try:
                if path in ("/", "/cabinet", "/cabinet/"):
                    self._send_file(CABINET_ROOT / "index.html")
                    return
                if path.startswith("/cabinet/"):
                    self._send_static(CABINET_ROOT, path.removeprefix("/cabinet/"))
                    return
                if path == "/api/me":
                    user = self._user()
                    if user:
                        self._send_json(HTTPStatus.OK, user)
                    return
                if path == "/api/projects":
                    user = self._user()
                    if user:
                        self._send_json(HTTPStatus.OK, {"projects": store.list_projects(user["id"])})
                    return
                project_id, rest = _project_route(path)
                if project_id and rest == "":
                    user = self._user()
                    if user:
                        self._send_json(HTTPStatus.OK, store.get_project(user["id"], project_id))
                    return
                if project_id and rest == "/file":
                    user = self._user()
                    if not user:
                        return
                    token = store.token_for(user["id"], project_id)
                    file_path = unquote(query.get("path", [""])[0])
                    text = read_file(store.job_dir(project_id), file_path, token)
                    self._send_json(HTTPStatus.OK, {"path": safe_repo_path(file_path), "text": text})
                    return
                if project_id is None and path.startswith("/p/"):
                    self._serve_map(path)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
            except (LookupError, FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
                self._error(exc)

        def do_POST(self) -> None:
            """Create a session, a project, a tree, or a map."""
            path, _query = _split(self.path)
            try:
                body = self._read_json()
                if path == "/api/register":
                    account = store.register(str(body.get("username") or ""), str(body.get("password") or ""))
                    session = store.open_session(account["username"], str(body.get("password") or ""))
                    self._send_json(HTTPStatus.CREATED, {"username": account["username"]}, session=session)
                    return
                if path == "/api/login":
                    session = store.open_session(str(body.get("username") or ""), str(body.get("password") or ""))
                    user = store.user_for_session(session)
                    self._send_json(HTTPStatus.OK, user or {}, session=session)
                    return
                if path == "/api/logout":
                    raw = self._session_cookie()
                    if raw:
                        store.close_session(raw)
                    self._send_json(HTTPStatus.OK, {"ok": True}, clear_session=True)
                    return
                if path == "/api/projects":
                    user = self._user()
                    if not user:
                        return
                    project = store.create_project(
                        user["id"],
                        str(body.get("name") or ""),
                        str(body.get("url") or ""),
                        str(body.get("token") or ""),
                    )
                    self._send_json(HTTPStatus.CREATED, project)
                    return
                if path.startswith("/p/"):
                    self._save_layout(path, body)
                    return
                project_id, rest = _project_route(path)
                if project_id and rest == "/tree":
                    user = self._user()
                    if not user:
                        return
                    project = store.get_project(user["id"], project_id)
                    files = sync_tree(store.job_dir(project_id), project["url"], store.token_for(user["id"], project_id))
                    self._send_json(HTTPStatus.OK, {"files": files})
                    return
                if project_id and rest == "/trace":
                    user = self._user()
                    if not user:
                        return
                    project = store.get_project(user["id"], project_id)
                    if not project["entries"]:
                        raise ValueError("Сначала укажите точку входа")
                    token = store.token_for(user["id"], project_id)
                    if not (store.job_dir(project_id) / "checkout" / ".git").is_dir():
                        sync_tree(store.job_dir(project_id), project["url"], token)
                    materialize_worktree(store.job_dir(project_id), token)
                    graph = trace_job(store.job_dir(project_id), token=token)
                    stats = graph.stats()
                    self._send_json(HTTPStatus.OK, {"node_count": stats["node_count"], "edge_count": stats["edge_count"]})
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
            except (LookupError, FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
                self._error(exc)

        def do_PATCH(self) -> None:
            """Update a project. A missing token keeps the saved secret."""
            path, _query = _split(self.path)
            try:
                project_id, rest = _project_route(path)
                if not project_id or rest:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                    return
                user = self._user()
                if not user:
                    return
                body = self._read_json()
                project = store.update_project(
                    user["id"],
                    project_id,
                    name=body.get("name"),
                    url=body.get("url"),
                    token=body.get("token"),
                )
                self._send_json(HTTPStatus.OK, project)
            except (LookupError, FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
                self._error(exc)

        def do_PUT(self) -> None:
            """Replace the entry point."""
            path, _query = _split(self.path)
            try:
                project_id, rest = _project_route(path)
                if not project_id or rest != "/entry":
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                    return
                user = self._user()
                if not user:
                    return
                body = self._read_json()
                project = store.set_entry(user["id"], project_id, str(body.get("entry") or ""))
                self._send_json(HTTPStatus.OK, project)
            except (LookupError, FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
                self._error(exc)

        def _save_layout(self, path: str, payload: dict) -> None:
            """Write layouts/<name>.json for the project owner."""
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) != 4 or parts[0] != "p" or parts[2] != "layouts":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            user = self._user()
            if not user:
                return
            project_id = parts[1]
            if not PROJECT_ID_RE.fullmatch(project_id):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            store.get_project(user["id"], project_id)
            name = _layout_name("/layouts/" + parts[3])
            if not name:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            payload["name"] = name
            payload.setdefault("saved_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            target = store.job_dir(project_id) / "layouts" / f"{name}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(HTTPStatus.OK, {"name": name, "saved_at": payload["saved_at"]})

        def _serve_map(self, path: str) -> None:
            """Serve one owner's map and its viewer files."""
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) < 2 or not PROJECT_ID_RE.fullmatch(parts[1]):
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            user = self._user()
            if not user:
                return
            project_id = parts[1]
            store.get_project(user["id"], project_id)
            job_dir = store.job_dir(project_id)
            tail = parts[2:]
            if tail == ["output", "execution_graph.json"]:
                if not (job_dir / "execution_graph.json").exists():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Карта ещё не построена"})
                    return
                self._send_json(HTTPStatus.OK, view_payload(job_dir))
                return
            if tail and tail[0] == "layouts":
                self._layouts(job_dir, "/".join(tail))
                return
            if tail and tail[0] == "viewer":
                if len(tail) == 1:
                    self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                    self.send_header("Location", f"/p/{project_id}/viewer/")
                    self.end_headers()
                    return
                relative = "/".join(tail[1:]) or "index.html"
                self._send_static(TOOL_ROOT / "viewer", relative)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})

        def _layouts(self, job_dir: Path, route: str) -> None:
            """Read a layout. Saving uses POST and is handled with the map prefix."""
            if route in ("layouts", "layouts/"):
                folder = job_dir / "layouts"
                folder.mkdir(parents=True, exist_ok=True)
                items = []
                for layout_path in sorted(folder.glob("*.json")):
                    try:
                        data = json.loads(layout_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    items.append({"name": layout_path.stem, "saved_at": data.get("saved_at"), "graph": data.get("graph")})
                self._send_json(HTTPStatus.OK, {"layouts": items})
                return
            name = _layout_name("/" + route)
            if not name:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            target = (job_dir / "layouts" / f"{name}.json").resolve()
            if job_dir.resolve() not in target.parents or not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            self._send_file(target)

        def _user(self) -> dict | None:
            """Current account, or 401."""
            user = store.user_for_session(self._session_cookie())
            if user is None:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Нужно войти"})
                return None
            return user

        def _session_cookie(self) -> str | None:
            """Raw session cookie."""
            header = self.headers.get("Cookie") or ""
            for part in header.split(";"):
                name, separator, value = part.strip().partition("=")
                if separator and name == "session" and value:
                    return value
            return None

        def _read_json(self) -> dict:
            """JSON object from the request body."""
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length > MAX_BODY:
                raise ValueError("Слишком большой запрос")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Нужен JSON") from exc
            if not isinstance(data, dict):
                raise ValueError("Нужен JSON-объект")
            return data

        def _error(self, exc: Exception) -> None:
            """Map a known failure to HTTP."""
            status = HTTPStatus.BAD_REQUEST
            if isinstance(exc, LookupError):
                status = HTTPStatus.NOT_FOUND
            elif isinstance(exc, FileNotFoundError):
                status = HTTPStatus.NOT_FOUND
            elif isinstance(exc, PermissionError):
                status = HTTPStatus.UNAUTHORIZED
            self._send_json(status, {"error": str(exc)})

        def _send_static(self, root: Path, relative: str) -> None:
            """Send one file that stays inside root."""
            relative = relative.split("?", 1)[0].lstrip("/")
            if relative in ("",):
                relative = "index.html"
            candidate = (root / relative).resolve()
            root_resolved = root.resolve()
            if candidate != root_resolved and root_resolved not in candidate.parents:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            if not candidate.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Не найдено"})
                return
            self._send_file(candidate)

        def _send_file(self, path: Path) -> None:
            """Send a file with a guessed content type."""
            body = path.read_bytes()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }.get(path.suffix, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(
            self,
            status: HTTPStatus,
            payload: dict,
            *,
            session: str | None = None,
            clear_session: bool = False,
        ) -> None:
            """Write JSON and, when asked, set or clear the session cookie."""
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if session is not None:
                self.send_header("Set-Cookie", f"session={session}; HttpOnly; Path=/; SameSite=Lax")
            if clear_session:
                self.send_header("Set-Cookie", "session=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            """Keep request lines on stderr without extra formatting."""
            print(f"{self.address_string()} {fmt % args}")

    return CabinetHandler


def _split(raw: str) -> tuple[str, dict[str, list[str]]]:
    """Path and query. The path has no trailing slash except the cabinet root."""
    parsed = urlparse(raw)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/") and not path.startswith("/p/"):
        path = path.rstrip("/")
    return path, parse_qs(parsed.query)


def _project_route(path: str) -> tuple[str | None, str]:
    """Split /api/projects/<id> and the remainder."""
    prefix = "/api/projects/"
    if path == "/api/projects":
        return None, ""
    if not path.startswith(prefix):
        return None, ""
    rest = path.removeprefix(prefix)
    project_id, separator, tail = rest.partition("/")
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise LookupError("Проект не найден")
    return project_id, f"/{tail}" if separator else ""
