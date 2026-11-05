from __future__ import annotations

from services.web_ui.data.graph import NodeKind, graph_stats, project_graph

from .context import UiServices, get_services
from .core import resolve_package


def get_graph(package: str | None = None, *,
              services: UiServices | None = None) -> dict:
    """Граф требований для экрана 2.15: проекция фактов/рёбер Knowledge."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return project_graph(services.knowledge.get_graph(package))


__all__ = ["NodeKind", "get_graph", "graph_stats", "project_graph"]
