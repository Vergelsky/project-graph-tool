"""Graph node types and model."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    ENTRY_POINT = "ENTRY_POINT"
    VIEW = "VIEW"
    SERVICE = "SERVICE"
    REPOSITORY = "REPOSITORY"
    MODEL = "MODEL"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    ORM = "ORM"
    DATABASE = "DATABASE"
    TABLE = "TABLE"
    SQL = "SQL"
    CACHE = "CACHE"
    QUEUE = "QUEUE"
    EVENT = "EVENT"
    SIGNAL = "SIGNAL"
    EXTERNAL_API = "EXTERNAL_API"
    FILE = "FILE"
    MODULE = "MODULE"
    PACKAGE = "PACKAGE"
    UNKNOWN = "UNKNOWN"


class Node(BaseModel):
    id: str
    type: NodeType
    name: str
    qualified_name: str
    description: str | None = None
    source_file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_export_dict(self) -> dict[str, Any]:
        """Serialize node for JSON export."""
        return self.model_dump(mode="json")
