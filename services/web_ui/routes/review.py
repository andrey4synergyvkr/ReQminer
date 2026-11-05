from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from services.web_ui.data import adapter
from services.web_ui.rendering import render

router = APIRouter()


# Меню «Противоречия» и кнопка «К подтверждению (N)» списка фактов (2.13 → 2.14).
@router.get("/review", response_class=HTMLResponse)
def review(request: Request, package: str = adapter.DEFAULT_PACKAGE):
    """Экран подтверждения фактов и пар."""
    package = adapter.resolve_package(package)
    data = adapter.review_data(package)
    return render(
        request, "review.html", "review",
        data=data, pkg=adapter.get_package(package),
        packages=adapter.list_packages(), package=package,
        pending_count=adapter.pending_count(package),
        fact_types=adapter.FACT_TYPES,
    )


# Кнопки «Подтвердить» / «Отклонить» / «Запросить уточнение» (рис. 2.14, секция фактов).
@router.post("/review/facts")
async def review_facts(request: Request):
    """Применяет решения по фактам и возвращает на экран."""
    form = await request.form()
    ids = form.getlist("fact_id")
    action = form.get("action", "")
    package = adapter.resolve_package(str(form.get("package") or ""))
    if ids and action:
        await run_in_threadpool(
            adapter.review_facts, [str(i) for i in ids], str(action), package
        )
    return RedirectResponse(f"/review?package={package}", status_code=303)


# Кнопки «Пометить как противоречие» / «Пометить как дубликат» /
# «Отклонить пару» (рис. 2.14, секция пар-кандидатов).
@router.post("/review/pairs")
async def review_pairs(request: Request):
    """Применяет решения по парам и возвращает на экран."""
    form = await request.form()
    ids = form.getlist("pair_id")
    action = form.get("action", "")
    package = adapter.resolve_package(str(form.get("package") or ""))

    def apply_decisions() -> None:
        for pid in ids:
            adapter.review_pair(str(pid), str(action), package)

    await run_in_threadpool(apply_decisions)
    return RedirectResponse(f"/review?package={package}", status_code=303)
