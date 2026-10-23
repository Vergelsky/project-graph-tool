"""Follow a project function passed into a library call, such as add_route(path, view)."""

from __future__ import annotations

from project_map.libraries.base import ProjectIndex, ProjectTarget, SeenCall


class CallbackBridge:
    """Enqueue project callables used as arguments of a non-project call."""

    name = "callbacks"

    def extra_targets(self, call: SeenCall, index: ProjectIndex) -> list[ProjectTarget]:
        """Return unique project functions named by the call arguments."""
        if call.expandable:
            return []
        names = list(call.argument_names)
        targets: list[ProjectTarget] = []
        seen: set[str] = set()
        for name in names:
            matches = index.named(name, prefer_file=None)
            if len(matches) != 1:
                continue
            target = matches[0]
            if target.qualified_name in seen:
                continue
            seen.add(target.qualified_name)
            targets.append(target)
        return targets
