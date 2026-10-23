"""Serve the existing viewer against one job folder."""

from __future__ import annotations

import json
import re
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from project_map.analyze.projection import project
from project_map.job import load_graph

TOOL_ROOT = Path(__file__).resolve().parent.parent
LAYOUT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
VIEW_LEVEL = "function"


def view_payload(job_dir: Path, level: str = VIEW_LEVEL) -> dict:
    """Projected graph with texts joined from descriptions.json. The graph file stays text-free."""
    projected = project(load_graph(job_dir), level)
    payload = projected.to_export_dict()
    records = _records(job_dir)
    by_key = {(item.get("level"), item.get("node_id")): item.get("text") for item in records}
    for node in payload["nodes"]:
        text = by_key.get((level, node["id"]))
        if text:
            node["description"] = text
    payload["meta"] = {"level": level}
    return payload


def serve_job(job_dir: Path, port: int) -> None:
    """Block and serve the viewer until interrupted."""
    job_dir = job_dir.resolve()
    if not (job_dir / "job.json").exists():
        raise FileNotFoundError(job_dir / "job.json")
    handler = _handler(job_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Map at http://127.0.0.1:{port}/viewer/")
    server.serve_forever()


def _records(job_dir: Path) -> list[dict]:
    """Description records, if the describe stage has run."""
    path = job_dir / "descriptions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("records") or [])


def _handler(job_dir: Path) -> type[SimpleHTTPRequestHandler]:
    """HTTP handler bound to one job."""

    class JobHandler(SimpleHTTPRequestHandler):
        """Serve viewer assets, the projected graph, and layouts/<level>.json."""

        def do_GET(self) -> None:
            """Projected graph, layout list, or a static viewer file."""
            clean = self.path.split("?", 1)[0]
            if clean in ("/output/execution_graph.json", "/job/view.json"):
                self._send_json(HTTPStatus.OK, view_payload(job_dir))
                return
            if clean in ("/layouts", "/layouts/"):
                self._send_layout_list()
                return
            if clean == "/viewer":
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", "/viewer/")
                self.end_headers()
                return
            super().do_GET()

        def do_POST(self) -> None:
            """Save a layout under layouts/<name>.json inside the job."""
            name = _layout_name(self.path)
            if not name:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
                return
            if not isinstance(payload, dict):
                self.send_error(HTTPStatus.BAD_REQUEST, "Layout must be a JSON object")
                return
            payload["name"] = name
            payload.setdefault("saved_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            target = job_dir / "layouts" / f"{name}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(HTTPStatus.OK, {"name": name, "saved_at": payload["saved_at"]})

        def translate_path(self, path: str) -> str:
            """Map viewer URLs onto the tool viewer and job layouts."""
            clean = path.split("?", 1)[0].split("#", 1)[0]
            if clean in ("", "/"):
                return str(TOOL_ROOT / "viewer" / "index.html")
            if clean.startswith("/viewer/"):
                rel = clean.removeprefix("/viewer/") or "index.html"
                return str((TOOL_ROOT / "viewer" / rel).resolve())
            if clean.startswith("/layouts/"):
                rel = clean.removeprefix("/layouts/")
                return str((job_dir / "layouts" / rel).resolve())
            return str((TOOL_ROOT / clean.lstrip("/")).resolve())

        def _layouts_dir(self) -> Path:
            """Layout directory for this job."""
            path = job_dir / "layouts"
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _send_layout_list(self) -> None:
            """JSON list of saved layouts."""
            items = []
            for path in sorted(self._layouts_dir().glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                items.append({"name": path.stem, "saved_at": data.get("saved_at"), "graph": data.get("graph")})
            self._send_json(HTTPStatus.OK, {"layouts": items})

        def _send_json(self, status: int, payload: dict) -> None:
            """Write JSON."""
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return JobHandler


def _layout_name(path: str) -> str | None:
    """Safe layout name from /layouts/<name>.json."""
    clean = path.split("?", 1)[0]
    if not clean.startswith("/layouts/") or not clean.endswith(".json"):
        return None
    name = clean.removeprefix("/layouts/").removesuffix(".json")
    if not LAYOUT_NAME_RE.fullmatch(name):
        return None
    return name
