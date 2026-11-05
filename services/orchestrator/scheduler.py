from __future__ import annotations

import threading

from contracts.workflow import PackageStatus
from services.common.logging import get_logger
from services.orchestrator import registry
from services.orchestrator.runner import run_package

log = get_logger("orchestrator.scheduler")

_active: set[str] = set()
_lock = threading.Lock()


def submit(pid: str) -> bool:
    """Запускает фоновый прогон пакета; False, если он уже выполняется."""
    pkg = registry.get_package(pid)
    if pkg is None or pkg["status"] == PackageStatus.REJECT:
        log.info("Прогон %s отклонен: пакет отсутствует или отклонен", pid)
        return False
    with _lock:
        if pid in _active:
            log.info("Прогон %s отклонен: уже выполняется", pid)
            return False
        _active.add(pid)
    log.info("Прогон %s принят: фоновый поток запущен", pid)
    threading.Thread(target=_run, args=(pid,), daemon=True).start()
    return True


def active(pid: str) -> bool:
    """Выполняется ли прогон пакета прямо сейчас."""
    with _lock:
        return pid in _active


def _run(pid: str) -> None:
    try:
        run_package(pid)
    finally:
        with _lock:
            _active.discard(pid)
