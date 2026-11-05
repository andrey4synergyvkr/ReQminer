from __future__ import annotations

from contracts.workflow import PackageStatus, RunState
from services.orchestrator.progress import PHASE_DEFS

from .context import UiServices, get_services
from .progress_data import (
    TERMINAL,
    counter,
    eta_label,
    percent,
    phase_index,
    progress_of,
    stale_warning,
    steps,
)
from .run import get_run_view, run_state_line


def _title(pkg: dict, run: dict, phase_title: str) -> str:
    if pkg.get("status") == PackageStatus.REJECT.value:
        return "Прогон отклонён"
    state = run.get("state")
    if state == RunState.FAILED.value:
        return "Прогон прерван"
    if state == RunState.CONFIRM.value:
        return "Ожидает подтверждения"
    if state == RunState.DONE.value:
        return "Прогон завершён"
    if state == RunState.RUN.value:
        return phase_title
    return "Прогон не запущен"


def _css(pkg: dict, state: str) -> str:
    if pkg.get("status") == PackageStatus.REJECT.value:
        return "reject"
    if state == RunState.FAILED.value:
        return "failed"
    if state in TERMINAL:
        return "done"
    if state == RunState.RUN.value:
        return "run"
    return "wait"


def progress_view(pid: str, pkg: dict | None = None, run: dict | None = None,
                  *, services: UiServices | None = None) -> dict:
    """Данные карточки прогресса и степпера для экрана 2.12."""
    services = services or get_services()
    if pkg is None:
        pkg = services.registry.get_package(pid) or {}
    if run is None:
        run = get_run_view(pid, pkg, services=services)
    index = phase_index(run)
    definition = PHASE_DEFS[index]
    value = percent(run)
    counter_text = counter(run, index)
    state = run.get("state", RunState.WAIT.value)
    return {
        "state": state,
        "percent": value,
        "title": _title(pkg, run, definition.title),
        "phase": definition.title,
        "index": index,
        "css": _css(pkg, state),
        "steps": steps(run, index, counter_text),
        "counter": counter_text,
        "detail": progress_of(run).get("detail") or "",
        "eta": eta_label(progress_of(run).get("eta_seconds")),
        "stale": stale_warning(run),
        "state_line": run_state_line(
            pid, services=services, pkg=pkg, run=run
        ),
        "aria_text": (
            f"{definition.title}, {counter_text}, {value} %" if counter_text
            else f"{definition.title}, {value} %"
        ),
    }
