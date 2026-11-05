from __future__ import annotations

from contracts.workflow import PackageStatus, RunState
from services.common.formats import format_iso_ts

from .context import UiServices, get_services
from .core import get_package
from .facts import pending_count


# Без кнопки: открытие экрана прогресса кнопкой «Открыть» (рис. 2.12)
# и автообновление панели HTMX-поллингом каждые POLL_SECONDS.
def get_run(pid: str, *, services: UiServices | None = None) -> dict | None:
    """Запись прогона пакета или None."""
    services = services or get_services()
    return services.registry.get_run(pid)


def get_run_view(pid: str, pkg: dict | None = None, *,
                 services: UiServices | None = None) -> dict:
    """Запись прогона для экранов; без записи - пустая заглушка.

    Состояние пакета не подставляется в поле состояния прогона: словари
    состояний разные («reject» у пакета, «failed» у прогона), и смешение
    давало мёртвые ветки в шаблоне.
    """
    services = services or get_services()
    run = services.registry.get_run(pid)
    if run is not None:
        return run
    pkg = pkg or services.registry.get_package(pid) or {}
    state = pkg.get("status")
    return {
        "state": state if state in (
            PackageStatus.RUN.value,
            PackageStatus.CONFIRM.value,
            PackageStatus.DONE.value,
            PackageStatus.FAILED.value,
        ) else RunState.WAIT.value,
        "started": "",
        "finished": "",
        "stages": [],
        "metrics": {},
    }


# Без кнопки: строка состояния под заголовком экранов прогона и отчёта.
def run_state_line(pid: str, *, services: UiServices | None = None,
                   pkg: dict | None = None, run: dict | None = None) -> str:
    """Строка состояния прогона для заголовка экрана."""
    services = services or get_services()
    pkg = pkg if pkg is not None else get_package(pid, services=services)
    run = run if run is not None else (get_run(pid, services=services) or {})
    if pkg is None:
        return ""
    if pkg["status"] == PackageStatus.REJECT:
        reason = pkg.get("reject_reason")
        return (
            f'Пакет <b>{pkg["name"]}</b> — прогон отклонен'
            + (f" ({reason})" if reason else "")
        )
    if pkg["status"] == PackageStatus.FAILED:
        detail = run.get("error") or "см. журнал"
        return f'Пакет <b>{pkg["name"]}</b> — прогон упал: {detail}'
    if run.get("state") == RunState.DONE:
        return f'Пакет <b>{pkg["name"]}</b> — прогон завершен {run["finished"]}'
    if run.get("state") == RunState.CONFIRM:
        return (
            f'Пакет <b>{pkg["name"]}</b> — ожидают подтверждения факты '
            f'({pending_count(pid, services=services)})'
        )
    if run.get("state") == RunState.RUN:
        started = format_iso_ts(run.get("started", ""))
        return (
            f'Прогон выполняется <span class="badge run">в работе</span> '
            f'· начат {started}'
        )
    if run.get("state") == RunState.FAILED:
        return f'Пакет <b>{pkg["name"]}</b> — прогон упал: {run.get("error", "")}'
    return f'Пакет <b>{pkg["name"]}</b>'
