from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from services.web_ui.data import adapter
from services.web_ui.rendering import render

router = APIRouter()


# Меню «Факты» и кнопка «Перейти к фактам» экрана прогресса (2.12 → 2.13).
@router.get("/facts", response_class=HTMLResponse)
def facts(
    request: Request,
    package: str = adapter.DEFAULT_PACKAGE,
    type: str = "все",  # noqa: A002 - имя query-параметра
    status: str = "все",
    min_conf: str = "0.70",
    q: str = "",
):
    """Экран «Факты» с фильтрами."""
    package = adapter.resolve_package(package)
    rows = adapter.list_facts(package, type, status, min_conf, q)
    return render(
        request, "facts.html", "facts",
        rows=rows, fact_types=adapter.FACT_TYPES,
        fact_status_labels=adapter.FACT_STATUS_LABELS,
        fact_status_css=adapter.FACT_STATUS_CSS,
        pending_count=adapter.pending_count(package),
        total=adapter.facts_total(package),
        pkg=adapter.get_package(package),
        packages=adapter.list_packages(), package=package,
        f_type=type, f_status=status, f_min_conf=min_conf, f_q=q,
    )


# Клик по ссылке источника в таблице фактов (рис. 2.13) - диалог фрагмента;
# из графа - кнопка «Перейти к фрагменту-источнику» (рис. 2.15).
@router.get("/facts/{fid}/fragment")
def fact_fragment(fid: str, package: str = adapter.DEFAULT_PACKAGE):
    """Фрагмент-источник факта для диалога."""
    package = adapter.resolve_package(package)
    fact = adapter.get_fact(fid, package)
    if fact is None:
        return Response("Факт не найден", status_code=404)
    frag = adapter.get_fragment(fact["doc"], fact["frag"], package)
    if frag is None:
        return Response("Фрагмент не найден", status_code=404)
    return {
        "title": (
            f'{frag["doc"]}, фрагмент {frag["frag"]} — '
            f'источник факта {fact["id"]}'
        ),
        "text": frag["text"],
    }
