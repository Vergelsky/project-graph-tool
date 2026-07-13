"""Serve viewer UI, output, and layout configs from data-repo."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
LAYOUT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def make_handler(data_root: Path) -> type[SimpleHTTPRequestHandler]:
    """Build request handler bound to tool and data roots."""
    workspace_root = data_root

    class DualRootHandler(SimpleHTTPRequestHandler):
        """Serve /viewer, /output, and /layouts from tool and data roots."""

        def translate_path(self, path: str) -> str:
            """Map URL path to filesystem path."""
            clean = path.split("?", 1)[0].split("#", 1)[0]
            if clean in ("", "/"):
                return str(TOOL_ROOT / "viewer" / "index.html")
            if clean.startswith("/viewer/"):
                rel = clean.removeprefix("/viewer/") or "index.html"
                return str(TOOL_ROOT / "viewer" / rel)
            if clean.startswith("/output/"):
                rel = clean.removeprefix("/output/")
                return str(workspace_root / "output" / rel)
            if clean.startswith("/layouts/"):
                rel = clean.removeprefix("/layouts/")
                return str(workspace_root / "layouts" / rel)
            return str(TOOL_ROOT / clean.lstrip("/"))

        def _layouts_dir(self) -> Path:
            """Return layouts directory, creating it if needed."""
            path = workspace_root / "layouts"
            path.mkdir(parents=True, exist_ok=True)
            return path

        def _send_json(self, status: int, payload: dict) -> None:
            """Write a JSON HTTP response."""
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _parse_layout_name(self, path: str) -> str | None:
            """Extract a safe layout name from /layouts/<name>.json."""
            clean = path.split("?", 1)[0]
            if not clean.startswith("/layouts/") or not clean.endswith(".json"):
                return None
            name = clean.removeprefix("/layouts/").removesuffix(".json")
            if not LAYOUT_NAME_RE.fullmatch(name):
                return None
            return name

        def _send_layout_list(self) -> None:
            """Return JSON list of saved layout configs."""
            items: list[dict] = []
            for path in sorted(self._layouts_dir().glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                items.append(
                    {
                        "name": path.stem,
                        "saved_at": data.get("saved_at"),
                        "graph": data.get("graph"),
                    }
                )
            self._send_json(HTTPStatus.OK, {"layouts": items})

        def do_GET(self) -> None:
            """Handle viewer redirect and layout listing."""
            if self.path == "/viewer":
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header("Location", "/viewer/")
                self.end_headers()
                return
            clean = self.path.split("?", 1)[0]
            if clean in ("/layouts", "/layouts/"):
                self._send_layout_list()
                return
            super().do_GET()

        def do_POST(self) -> None:
            """Save a named layout config to data-repo."""
            name = self._parse_layout_name(self.path)
            if not name:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
                return
            if not isinstance(payload, dict):
                self.send_error(HTTPStatus.BAD_REQUEST, "Layout must be a JSON object")
                return

            payload["name"] = name
            payload.setdefault("saved_at", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
            target = self._layouts_dir() / f"{name}.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(HTTPStatus.OK, {"name": name, "saved_at": payload["saved_at"]})

    return DualRootHandler


def main() -> None:
    """Start local viewer server."""
    parser = argparse.ArgumentParser(description="Serve Project Execution Map viewer")
    parser.add_argument("--data-dir", required=True, help="Data workspace directory")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port")
    args = parser.parse_args()

    data_root = Path(args.data_dir).expanduser().resolve()
    workspace_file = data_root / "workspace.yaml"
    if not workspace_file.exists():
        raise SystemExit(f"Missing workspace.yaml in data directory: {data_root}")

    handler = make_handler(data_root)
    server = ThreadingHTTPServer(("", args.port), handler)
    (data_root / "layouts").mkdir(parents=True, exist_ok=True)
    print(f"Viewer:  http://127.0.0.1:{args.port}/viewer/")
    print(f"Output:  {data_root / 'output'}")
    print(f"Layouts: {data_root / 'layouts'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
