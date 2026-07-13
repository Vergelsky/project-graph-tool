"""Pydantic models for trace root pointers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class TracePointer(BaseModel):
    """Pointer to a function definition or call site."""

    kind: Literal["def", "call"]
    qualified_name: str | None = None
    file: str | None = None
    line: int | None = None

    @model_validator(mode="after")
    def validate_pointer(self) -> TracePointer:
        """Validate pointer fields for kind."""
        if self.kind == "def":
            if self.qualified_name:
                return self
            if self.file and self.line:
                return self
            raise ValueError("def pointer requires qualified_name or file+line")
        if self.file and self.line:
            return self
        raise ValueError("call pointer requires file+line")


class TraceRoot(BaseModel):
    """A trace root with optional id."""

    id: str | None = None
    pointer: TracePointer


class TraceDoneEntry(BaseModel):
    """Processed trace root record."""

    id: str
    pointer: TracePointer
    processed_at: str
    node_count: int = 0
    edge_count: int = 0
