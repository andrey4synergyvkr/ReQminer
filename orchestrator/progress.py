from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from contracts.records import Run
from contracts.stores import RunStore
from contracts.workflow import Phase, RunState, StageStatus

# UI поллит раз в 3 с: чаще писать в реестр смысла нет (п. 2.5 проекта).
THROTTLE_SECONDS = 0.75
# Прогон без heartbeat дольше этого срока считается зависшим (экран 2.12).
STALE_AFTER_SECONDS = 180
MIN_ETA_PERCENT = 5
MIN_ETA_ELAPSED = 5.0


@dataclass(frozen=True)
class PhaseDef:
    """Фаза конвейера: подписи, единица счёта и вес в общем проценте."""

    phase: Phase
    service: str
    mod: str
    title: str
    unit: str
    unit_plural: str
    weight: int
    short: str


PHASE_DEFS = (
    PhaseDef(
        Phase.INGEST, "Ingestor", "нарезка и парсинг документов",
        "Приём документов", "документ", "документов", 5, "Приём",
    ),
    PhaseDef(
        Phase.EXTRACT, "Extractor", "извлечение и валидация фактов",
        "Извлечение фактов", "фрагмент", "фрагментов", 55, "Извлечение",
    ),
    PhaseDef(
        Phase.PAIRING, "Extractor", "выявление противоречий",
        "Выявление противоречий", "пара", "пар", 20, "Противоречия",
    ),
    PhaseDef(
        Phase.BUILD, "Builder", "формирование каркаса",
        "Формирование каркаса", "раздел", "разделов", 20, "Каркас",
    ),
)

PHASE_INDEX = {definition.phase: index for index, definition in enumerate(PHASE_DEFS)}
TOTAL_WEIGHT = sum(definition.weight for definition in PHASE_DEFS)


class ProgressReporter:
    """Счётчик прогресса одного прогона и его запись в реестр.

    Единственный писатель прогресса: сервисы сообщают счётчики через tick,
    reporter сам обновляет запись прогона. Вызовы приходят из пула потоков,
    поэтому состояние защищено RLock, а запись троттлится под поллинг UI.
    Процент считается по весам фаз, монотонен и достигает 100 на финале.
    """

    def __init__(
        self,
        pid: str,
        run: Run,
        registry: RunStore,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pid = pid
        self._run = run
        self._registry = registry
        self._clock = clock
        self._lock = threading.RLock()
        self._started = clock()
        self._last_write = 0.0
        self._prev_percent = 0
        self._prev_eta = -1.0
        self._index = -1
        existing = run.get("progress") or {}
        self._updated = existing.get("updated") or _now()

    # --- команды runner-а ---------------------------------------------------

    def enter(self, phase: Phase) -> None:
        """Начало фазы: этап в работе, процент - на левой границе."""
        with self._lock:
            index = PHASE_INDEX[phase]
            self._index = index
            self._prev_eta = -1.0
            definition = PHASE_DEFS[index]
            self._stage.update(
                status=StageStatus.RUN.value,
                processed="выполняется",
                done=0,
                total=0,
                unit=definition.unit,
            )
            percent = self._percent(index, 0, 0, complete=False)
            self._run["progress"] = self._record(index, 0, 0, "", percent)
            self._write(force=True)

    def tick(self, done: int, total: int, detail: str = "") -> None:
        """Единица работы завершена: счётчик, процент и (с троттлингом) запись."""
        with self._lock:
            if self._index < 0:
                return
            # тики конкурентных вызовов могут прийти не по порядку: счётчик
            # не откатываем (лок сервиса выдаёт номера по завершению, а
            # очередь до reporter-а доходит в произвольном порядке)
            done = max(done, int(self._stage.get("done") or 0))
            percent = self._percent(self._index, done, total, complete=False)
            definition = PHASE_DEFS[self._index]
            self._stage.update(
                status=StageStatus.RUN.value, done=done, total=total,
                unit=definition.unit,
            )
            self._stage["processed"] = (
                f"{done} из {total} {definition.unit_plural}"
                if total > 0 else "выполняется"
            )
            self._run["progress"] = self._record(
                self._index, done, total, detail, percent
            )
            self._write()

    def finish_phase(self, processed: str) -> None:
        """Фаза завершена: этап done, процент - на правой границе."""
        with self._lock:
            if self._index < 0:
                return
            index = self._index
            total = self._stage.get("total") or self._stage.get("done") or 0
            self._stage.update(
                status=StageStatus.DONE.value, processed=processed,
                done=total, total=total,
            )
            self._prev_eta = -1.0
            percent = self._percent(index, total, total, complete=True)
            self._run["progress"] = self._record(index, total, total, "", percent)
            self._write(force=True)

    def finish(self, state: RunState) -> None:
        """Финал прогона: 100 % - только здесь (done/confirm)."""
        assert state in (RunState.DONE, RunState.CONFIRM), (
            "100 % ставится только терминальному прогону"
        )
        with self._lock:
            index = max(self._index, 0)
            progress = self._run.setdefault("progress", {})
            total = progress.get("total") or 0
            progress.update({
                "phase": PHASE_DEFS[index].phase.value,
                "phase_index": index,
                "phases_total": len(PHASE_DEFS),
                "percent": 100,
                "done": total,
                "total": total,
                "unit": progress.get("unit") or PHASE_DEFS[index].unit,
                "detail": "",
                "eta_seconds": 0,
                "updated": self._updated,
            })
            self._prev_percent = 100
            self._write(force=True)

    def fail(self, error: str) -> None:
        """Сбой: процент сохраняется, heartbeat обновляется для экрана."""
        with self._lock:
            progress = self._run.setdefault("progress", {})
            progress["eta_seconds"] = -1
            if error and not self._run.get("error"):
                self._run["error"] = error
            self._write(force=True)

    # --- внутреннее ---------------------------------------------------------

    @property
    def _stage(self) -> dict:
        stages = self._run.get("stages") or []
        assert 0 <= self._index < len(stages), "этап отсутствует в записи прогона"
        return stages[self._index]

    def _percent(self, index: int, done: int, total: int, *, complete: bool) -> int:
        """Весовая доля работы; монотонно, 100 - только на финале."""
        before = sum(item.weight for item in PHASE_DEFS[:index])
        share = PHASE_DEFS[index].weight
        if complete:
            frac = 1.0
        elif total > 0:
            frac = min(max(done, 0) / total, 1.0)
        else:
            frac = 0.0
        value = round(before + share * frac)
        value = max(self._prev_percent, min(value, 99))
        self._prev_percent = value
        return value

    def _eta(self, percent: int) -> int:
        """Линейная экстраполяция остатка со сглаживанием; -1 - мало данных."""
        elapsed = self._clock() - self._started
        if percent < MIN_ETA_PERCENT or elapsed < MIN_ETA_ELAPSED:
            return -1
        raw = elapsed * (100 - percent) / percent
        eta = raw if self._prev_eta < 0 else 0.7 * self._prev_eta + 0.3 * raw
        self._prev_eta = eta
        return max(0, round(eta))

    def _record(
        self, index: int, done: int, total: int, detail: str, percent: int
    ) -> dict:
        definition = PHASE_DEFS[index]
        return {
            "phase": definition.phase.value,
            "phase_index": index,
            "phases_total": len(PHASE_DEFS),
            "percent": percent,
            "done": done,
            "total": total,
            "unit": definition.unit,
            "detail": detail,
            "eta_seconds": self._eta(percent),
            "updated": self._updated,
        }

    def _write(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_write < THROTTLE_SECONDS:
            return
        self._last_write = now
        self._updated = _now()
        self._run.setdefault("progress", {})["updated"] = self._updated
        self._registry.set_run(self._pid, self._run)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
