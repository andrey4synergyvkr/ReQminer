from __future__ import annotations

from datetime import datetime

from contracts.workflow import RunState, StageStatus
from services.orchestrator.progress import PHASE_DEFS, STALE_AFTER_SECONDS

from .context import UiServices, get_services

TERMINAL = (RunState.DONE.value, RunState.CONFIRM.value)
_STATUSES = {status.value for status in StageStatus}


def progress_of(run: dict) -> dict:
    """Запись прогресса прогона; пустой словарь, если её нет."""
    return run.get("progress") or {}


def phase_index(run: dict) -> int:
    """Индекс текущей фазы: из записи прогресса или по статусам этапов."""
    index = progress_of(run).get("phase_index")
    if isinstance(index, int) and 0 <= index < len(PHASE_DEFS):
        return index
    stages = run.get("stages") or []
    for i, stage in enumerate(stages[: len(PHASE_DEFS)]):
        if stage.get("status") == StageStatus.RUN.value:
            return i
    if run.get("state") in TERMINAL:
        return len(PHASE_DEFS) - 1
    return 0


def percent(run: dict) -> int:
    """Процент: из записи прогресса, иначе по завершённым этапам (сиды)."""
    if run.get("state") in TERMINAL:
        return 100
    value = progress_of(run).get("percent")
    if isinstance(value, int):
        return max(0, min(value, 99))
    stages = run.get("stages") or []
    total = 0.0
    for i, definition in enumerate(PHASE_DEFS):
        status = stages[i].get("status") if i < len(stages) else None
        if status == StageStatus.DONE.value:
            total += definition.weight
        elif status == StageStatus.RUN.value:
            done = stages[i].get("done") or 0
            unit_total = stages[i].get("total") or 0
            if unit_total > 0:
                total += definition.weight * min(done / unit_total, 1.0)
    return max(0, min(round(total), 99))


def counter(run: dict, index: int) -> str:
    """«5 из 12 пар» для текущей фазы; пусто, если счётчика нет."""
    progress = progress_of(run)
    done = progress.get("done")
    total = progress.get("total")
    if not isinstance(total, int) or total <= 0:
        stages = run.get("stages") or []
        stage = stages[index] if index < len(stages) else {}
        done = stage.get("done") or 0
        total = stage.get("total") or 0
        if total <= 0:
            return ""
    return f"{done or 0} из {total} {PHASE_DEFS[index].unit_plural}"


def eta_label(seconds: int | None) -> str:
    """Округлая оценка остатка: без ложной точности (п. 2.4 проекта)."""
    if not isinstance(seconds, int) or seconds < 0:
        return ""
    if seconds < 60:
        return "меньше минуты"
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"≈ {minutes} мин"
    return f"≈ {round(minutes / 60)} ч"


def stale_warning(run: dict, *, now: datetime | None = None) -> str:
    """Прогон в состоянии run без heartbeat дольше STALE_AFTER_SECONDS."""
    if run.get("state") != RunState.RUN.value:
        return ""
    updated = progress_of(run).get("updated")
    if not updated:
        return ""
    try:
        moment = datetime.fromisoformat(updated)
    except (TypeError, ValueError):
        return ""
    seconds = ((now or datetime.now()) - moment).total_seconds()
    if seconds < STALE_AFTER_SECONDS:
        return ""
    return (
        f"нет обновлений {int(seconds // 60)} мин — прогон мог прерваться; "
        "перезапустите кнопкой «Анализ»"
    )


def steps(run: dict, index: int, counter_text: str) -> list[dict]:
    """Четыре шага степпера: состояние, метка, подпись, текущий шаг."""
    stages = run.get("stages") or []
    # пакет уже в терминальном состоянии, а записи этапов нет (сид/старый
    # прогон): шаги показываются завершёнными, а не «ожидание»
    fallback = (
        StageStatus.DONE.value if run.get("state") in TERMINAL
        else StageStatus.WAIT.value
    )
    result = []
    for i, definition in enumerate(PHASE_DEFS):
        status = stages[i].get("status") if i < len(stages) else None
        if status not in _STATUSES:
            status = fallback
        result.append({
            "title": definition.short,
            "state": status,
            "mark": {"done": "✓", "run": "●", "failed": "✕"}.get(
                status, str(i + 1)
            ),
            "sub": (
                "завершён" if status == StageStatus.DONE.value
                else counter_text if status == StageStatus.RUN.value
                else "ошибка" if status == StageStatus.FAILED.value
                else ""
            ),
            "current": status == StageStatus.RUN.value and i == index,
        })
    return result


def progress_percent(pid: str, *, services: UiServices | None = None) -> int:
    """Процент активного прогона для строки реестра (2.10)."""
    services = services or get_services()
    return percent(services.registry.get_run(pid) or {})
