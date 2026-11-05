from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from services.web_ui.data import adapter
from services.web_ui.rendering import render

router = APIRouter()

# Предел размера одного загружаемого файла (защита памяти процесса).
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


# Открытие раздела: меню «Пакеты», кнопки «Применить» / «Сбросить фильтры».
@router.get("/", response_class=HTMLResponse)
def index():
    """Перенаправляет на список пакетов."""
    return RedirectResponse("/packages", status_code=302)


# Кнопки «Применить» и «Сбросить фильтры» реестра пакетов (рис. 2.10).
@router.get("/packages", response_class=HTMLResponse)
def packages(request: Request, direction: str = "все", status: str = "все",
             q: str = ""):
    """Экран реестра пакетов с фильтрами."""
    rows = adapter.list_packages(direction, status, q)
    return render(
        request, "packages.html", "packages",
        rows=rows, directions=adapter.DIRECTIONS,
        package_status_labels=adapter.PACKAGE_STATUS_LABELS,
        f_direction=direction, f_status=status, f_q=q,
    )


# Кнопка «Анализ» в подвале реестра пакетов (рис. 2.10, выделенная строка).
# 409: прогон пакета уже выполняется - планировщик отклонил повторный запуск.
@router.post("/packages/{pid}/analyze")
def analyze_package(pid: str):
    """Запускает анализ пакета; 409, если прогон уже идёт."""
    if not adapter.start_analysis(pid):
        return Response("Прогон уже выполняется", status_code=409)
    return RedirectResponse("/packages", status_code=303)


# Кнопка «Новый пакет» реестра пакетов (рис. 2.10 → форма 2.11).
@router.get("/packages/new", response_class=HTMLResponse)
def package_new(request: Request, invalid: int = 0):
    """Форма создания пакета."""
    return render(
        request, "package_new.html", "packages",
        directions=adapter.DIRECTIONS, doc_types=adapter.DOC_TYPES,
        allowed=sorted(adapter.ALLOWED_FORMATS.values()),
        invalid=invalid,
    )


# Кнопка «Анализ» формы приёма пакета (рис. 2.11); этапы формы:
# «Добавить файлы», «Убрать выбранные» обрабатываются на клиенте (app.js).
@router.post("/packages")
async def package_create(request: Request):
    """Принимает форму пакета и запускает анализ."""
    form = await request.form()
    uploads = form.getlist("files")
    staged = []
    for i, f in enumerate(uploads):
        if not getattr(f, "filename", ""):
            continue
        content = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            return Response(
                f"Файл {f.filename} больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ",
                status_code=413,
            )
        staged.append({
            "name": f.filename,
            "type": form.get(f"filetype-{i}", "не определен"),
            "content": content,
        })
    name = (form.get("name") or "").strip() or "Новый пакет"
    direction = form.get("direction") or adapter.DIRECTIONS[0]
    # запись файлов, SQL и запуск прогона - блокирующие: не держим event loop
    await run_in_threadpool(adapter.create_package, name, direction, staged)
    return RedirectResponse("/packages", status_code=303)


# Кнопка «Открыть» реестра пакетов (рис. 2.10 → 2.12);
# кнопки «Обновить» и «Перейти к фактам» - ссылки этого экрана.
@router.get("/packages/{pid}/run", response_class=HTMLResponse)
def run_progress(request: Request, pid: str):
    """Экран прогресса прогона."""
    pkg = adapter.get_package(pid)
    if pkg is None:
        return RedirectResponse("/packages", status_code=302)
    run = adapter.get_run_view(pid, pkg)
    view = adapter.progress_view(pid, pkg, run)
    return render(
        request, "run_progress.html", "packages",
        pkg=pkg, run=run, view=view, poll_seconds=adapter.POLL_SECONDS,
    )


# Без кнопки: HTMX-фрагмент панели прогресса, автообновление каждые
# POLL_SECONDS, пока прогон в состоянии «выполняется» (рис. 2.12).
@router.get("/packages/{pid}/run/panel", response_class=HTMLResponse)
def run_panel(request: Request, pid: str):
    """HTMX-фрагмент панели прогресса."""
    pkg = adapter.get_package(pid)
    if pkg is None:
        return Response("Пакет не найден", status_code=404)
    run = adapter.get_run_view(pid, pkg)
    view = adapter.progress_view(pid, pkg, run)
    return render(
        request, "_run_panel.html", "packages",
        pkg=pkg, run=run, view=view, poll_seconds=adapter.POLL_SECONDS,
    )


# Без кнопки: глобальная пилюля активного прогона в шапке (п. 5.3).
# Пустой фрагмент при отсутствии активных прогонов.
@router.get("/run-pill", response_class=HTMLResponse)
def run_pill(request: Request):
    """Пилюля активного прогона в шапке."""
    return render(
        request, "_run_pill.html", "packages", pill=adapter.active_run()
    )
