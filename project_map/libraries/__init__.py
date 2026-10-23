"""Built-in library bridges. Framework modules register beside CallbackBridge."""

from project_map.libraries.base import LibraryBridge, ProjectIndex, ProjectTarget, SeenCall
from project_map.libraries.callbacks import CallbackBridge

__all__ = ["CallbackBridge", "LibraryBridge", "ProjectIndex", "ProjectTarget", "SeenCall"]


def default_bridges() -> list[LibraryBridge]:
    """Bridges shipped with the core. Add a framework by appending another instance."""
    return [CallbackBridge()]
