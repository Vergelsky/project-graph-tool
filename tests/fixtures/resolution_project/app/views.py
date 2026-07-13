import json

from app.services import Service


def endpoint() -> str:
    payload = json.dumps({"ok": True})
    return Service.run(payload)


def shallow() -> None:
    json.loads("{}")
