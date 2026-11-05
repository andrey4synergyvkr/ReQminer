from __future__ import annotations

from contracts.workflow import RunState
from services.builder import service as builder
from services.orchestrator.metrics import collect

from .context import UiServices, get_services
from .core import get_package, resolve_package
from .run import get_run

OUTBOX_SECTIONS = builder.OUTBOX_SECTIONS


# Без кнопки: открытие экрана «Отчёты» (меню, рис. 2.16); для пакета
# без завершённого прогона отдаёт пустое состояние.
def get_report(package: str | None = None, *,
               services: UiServices | None = None) -> dict | None:
    """Собирает данные формы «Результаты прогона» (каркас + аналитический отчёт)."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    run = get_run(package, services=services)
    pkg = get_package(package, services=services)
    if pkg is None or run is None or run.get("state") not in (
        RunState.DONE, RunState.CONFIRM
    ):
        return None
    # один снимок фактов и пар на страницу: разделы каркаса, метрики и пробелы
    # модели считаются из него (в Neo4j-режиме list_facts - запрос на вызов)
    facts = services.knowledge.list_facts(package)
    pairs = services.knowledge.pairs_of(package)
    sections = [
        {**s, "facts": sum(1 for f in facts if f["type"] in s["types"])}
        for s in OUTBOX_SECTIONS
    ]
    metrics = collect(package, {
        "documents": pkg["documents"],
        "fragments": run["metrics"].get("fragments", 0),
        "quarantine": run["metrics"].get("quarantine", 0),
    }, facts=facts, pairs=pairs)
    return {
        "package": pkg,
        "finished": run["finished"],
        "sections": sections,
        "metrics": metrics,
        "gaps": services.builder.gaps_text(facts),
    }


# Кнопка «Просмотр» экрана отчёта (рис. 2.16) - диалог предпросмотра каркаса.
def get_outbox_doc(package: str, rel_path: str, *,
                   services: UiServices | None = None) -> str | None:
    """Читает файл каркаса из outbox пакета (через Builder)."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return services.builder.get_doc(package, rel_path)


# Кнопка «Экспорт в markdown» экрана отчёта (рис. 2.16) - скачивание zip.
def export_outbox_zip(package: str | None = None, *,
                      services: UiServices | None = None) -> bytes:
    """Zip-архив каркаса пакета."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return services.builder.export_zip(package)
