from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from services.web_ui.data import adapter
from services.web_ui.rendering import render

router = APIRouter()


# Меню «Граф» (рис. 2.15); фильтры графа обрабатывает app.js на клиенте.
@router.get("/graph", response_class=HTMLResponse)
def graph(request: Request, package: str = adapter.DEFAULT_PACKAGE):
    """Экран «Граф» с проекцией знаний."""
    package = adapter.resolve_package(package)
    g = adapter.get_graph(package)
    n_facts, n_edges = adapter.graph_stats(g)
    return render(
        request, "graph.html", "graph",
        graph=g, n_facts=n_facts, n_edges=n_edges,
        fact_types=adapter.FACT_TYPES, pkg=adapter.get_package(package),
        packages=adapter.list_packages(), package=package,
    )


# Без кнопки: JSON-данные графа для app.js (инициализация cytoscape).
@router.get("/graph/data")
def graph_data(package: str = adapter.DEFAULT_PACKAGE):
    """JSON-данные графа для визуализации."""
    return adapter.get_graph(adapter.resolve_package(package))
