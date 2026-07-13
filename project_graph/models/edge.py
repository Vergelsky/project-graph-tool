"""Graph edge types and model."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EdgeType(StrEnum):
    CALLS = "CALLS"
    READS = "READS"
    WRITES = "WRITES"
    CREATES = "CREATES"
    UPDATES = "UPDATES"
    DELETES = "DELETES"
    RETURNS = "RETURNS"
    AWAITS = "AWAITS"
    EMITS = "EMITS"
    SUBSCRIBES = "SUBSCRIBES"
    USES = "USES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"


class Edge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    type: EdgeType
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def to_export_dict(self) -> dict[str, Any]:
        """Serialize edge for JSON export."""
        return {
            "from": self.from_node,
            "to": self.to_node,
            "type": self.type.value,
            "metadata": self.metadata,
        }
