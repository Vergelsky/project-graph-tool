"""Fill card texts through an OpenAI-compatible chat API."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Protocol

from project_map.models import Node, NodeType

from project_map.analyze.files import read_text
from project_map.analyze.projection import project
from project_map.job import load_graph, load_job
from project_map.source import ensure_checkout

DESCRIBED_TYPES = {NodeType.FUNCTION, NodeType.METHOD, NodeType.FILE, NodeType.PACKAGE}


class ChatClient(Protocol):
    """One-shot completion. A local model later is another implementation."""

    def complete(self, prompt: str) -> str:
        """Return the card text."""


class OpenAICompatibleClient:
    """POST {base_url}/chat/completions."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str) -> str:
        """Send one user message and return the assistant text."""
        payload = json.dumps(
            {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body["choices"][0]["message"]["content"]).strip()


def describe_job(job_dir: Path, client: ChatClient, *, level: str = "function") -> int:
    """Write descriptions for nodes whose source hash changed. Returns how many were generated."""
    job = load_job(job_dir)
    repo = ensure_checkout(job, job_dir)
    graph = project(load_graph(job_dir), level)
    records = _load_records(job_dir)
    index = {(item["level"], item["node_id"]): item for item in records}
    written = 0
    for node in graph.nodes:
        if node.type not in DESCRIBED_TYPES:
            continue
        digest = node_hash(repo, node)
        previous = index.get((level, node.id))
        if previous and previous.get("source_hash") == digest and previous.get("text"):
            continue
        text = client.complete(build_prompt(repo, graph, node))
        index[(level, node.id)] = {
            "level": level,
            "node_id": node.id,
            "source_hash": digest,
            "text": text,
        }
        written += 1
    _save_records(job_dir, list(index.values()))
    return written


def build_prompt(repo: Path, graph, node: Node) -> str:
    """Prompt for one card. File cards list members instead of concatenating their texts."""
    outgoing = _edge_names(graph, node.id, outgoing=True)
    incoming = _edge_names(graph, node.id, outgoing=False)
    members = node.metadata.get("member_names") or []
    source = _source_slice(repo, node)
    member_block = "\n".join(f"- {name}" for name in members) if members else "—"
    return (
        "Опиши назначение этого узла карты выполнения в одном или двух предложениях.\n"
        "Пиши, что он делает в сценарии, а не пересказывай код построчно.\n\n"
        f"Имя: {node.qualified_name}\n"
        f"Тип: {node.type.value}\n"
        f"Вызывает: {', '.join(outgoing) or '—'}\n"
        f"Его вызывают: {', '.join(incoming) or '—'}\n"
        f"Состав: \n{member_block}\n"
        f"Исходник:\n{source or '—'}\n"
    )


def node_hash(repo: Path, node: Node) -> str:
    """Hash the source slice, or the member list when the card is a collapsed file."""
    source = _source_slice(repo, node)
    if source:
        payload = source
    else:
        payload = "\n".join(node.metadata.get("member_names") or [node.qualified_name])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_slice(repo: Path, node: Node) -> str:
    """Lines of a function. Collapsed cards have no single slice."""
    if not node.source_file or not node.line_start or node.metadata.get("members"):
        return ""
    text = read_text(repo / node.source_file)
    if text is None:
        return ""
    lines = text.splitlines()
    start = max(0, node.line_start - 1)
    end = node.line_end or node.line_start
    return "\n".join(lines[start:end])


def _edge_names(graph, node_id: str, *, outgoing: bool) -> list[str]:
    """Qualified names on one side of a node."""
    names: list[str] = []
    for edge in graph.edges:
        other_id = edge.to_node if outgoing and edge.from_node == node_id else None
        if not outgoing and edge.to_node == node_id:
            other_id = edge.from_node
        if other_id is None:
            continue
        other = graph.get_node(other_id)
        names.append(other.qualified_name if other else other_id)
    return names


def _load_records(job_dir: Path) -> list[dict]:
    """Read description records."""
    path = job_dir / "descriptions.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("records") or [])


def _save_records(job_dir: Path, records: list[dict]) -> None:
    """Write description records."""
    path = job_dir / "descriptions.json"
    path.write_text(json.dumps({"records": records}, indent=2, ensure_ascii=False), encoding="utf-8")
