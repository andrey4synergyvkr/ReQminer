from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from services.web_ui.data import adapter
from services.web_ui.rendering import render

router = APIRouter()


# Меню «Отчёты» и кнопка «К пакету» экрана отчёта (рис. 2.16).
@router.get("/report", response_class=HTMLResponse)
def report(request: Request, package: str = adapter.DEFAULT_PACKAGE):
    """Экран результатов прогона."""
    package = adapter.resolve_package(package)
    data = adapter.get_report(package)
    return render(request, "report.html", "report", data=data, package=package,
                  pkg=adapter.get_package(package),
                  packages=adapter.list_packages())


# Кнопка «Просмотр» экрана отчёта (рис. 2.16) - диалог предпросмотра каркаса.
@router.get("/report/preview")
def report_preview(package: str = adapter.DEFAULT_PACKAGE, path: str = ""):
    """Предпросмотр каркаса: без path - все разделы outbox целиком."""
    package = adapter.resolve_package(package)
    if path:
        md = adapter.get_outbox_doc(package, path)
        if md is None:
            return Response("Файл не найден в каталоге outbox", status_code=404)
        return adapter.md_to_html(md)
    data = adapter.get_report(package)
    if data is None:
        return Response("Каркас не сформирован", status_code=404)
    parts = []
    for section in data["sections"]:
        files = section.get("files", [section["file"]])
        for rel in files:
            md = adapter.get_outbox_doc(package, rel)
            if md:
                parts.append(adapter.md_to_html(md))
    return "<hr>".join(parts)


# Кнопка «Экспорт в markdown» экрана отчёта (рис. 2.16) - скачивание zip.
@router.get("/report/export/md")
def report_export_md(package: str = adapter.DEFAULT_PACKAGE):
    """Скачивает zip-архив каркаса."""
    package = adapter.resolve_package(package)
    data = adapter.export_outbox_zip(package)
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="outbox-{package}.zip"'
        },
    )


# Кнопка «Скачать отчет» экрана отчёта (рис. 2.16) - скачивание analysis_report.md.
@router.get("/report/download")
def report_download(package: str = adapter.DEFAULT_PACKAGE):
    """Скачивает analysis_report.md."""
    package = adapter.resolve_package(package)
    md = adapter.get_outbox_doc(package, "analysis_report.md")
    if md is None:
        return Response("Отчёт не найден", status_code=404)
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="analysis-report-{package}.md"'
            )
        },
    )
