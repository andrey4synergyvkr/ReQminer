from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path

from contracts.records import Package, Run
from contracts.stores import SeedableRunStore
from contracts.workflow import PackageStatus
from demo.scenario import DEMO_PACKAGE
from services.common.backends import REGISTRY_SQL
from services.common.lazy_backend import LazyBackend
from services.common.logging import get_logger
from services.orchestrator.staging import (
    build_package,
    prepare_package_dir,
    prepare_staged,
)

log = get_logger("orchestrator.registry")

_DATA_DIR = Path(__file__).resolve().parent / "data"


class InMemoryRegistry:
    """In-memory реестр: dict/список с сидом контрольного примера.

    Прогон обновляет реестр из фонового потока, UI читает его поллингом:
    методы защищены RLock, прогон сохраняется снапшотом (как SQL-бэкенд),
    чтобы читатель не видел наполовину обновленные этапы.
    """

    def __init__(self) -> None:
        self.inbox_root: Path | None = None
        self._packages: list[Package] = []
        self._runs: dict[str, Run] = {}
        self._next_pkg_num = 43  # следующий номер пакета для формы приема
        self._configured = False
        self._lock = threading.RLock()

    def load_seeds(self) -> None:
        """Сиды контрольного примера грузятся только в пустой реестр."""
        with self._lock:
            if self._packages or self._runs:
                return
        with open(_DATA_DIR / "packages.json", encoding="utf-8") as f:
            packages = json.load(f)
        with open(_DATA_DIR / "runs.json", encoding="utf-8") as f:
            runs = json.load(f)
        with self._lock:
            if self._packages or self._runs:
                return
            self._packages = packages
            self._runs = runs

    def inbox_dir(self, package: str) -> Path:
        """Каталог пакета во входящих."""
        return (self.inbox_root or Path("inbox")) / package

    def list_packages(self) -> list[Package]:
        """Все пакеты реестра."""
        with self._lock:
            return copy.deepcopy(self._packages)

    def get_package(self, pid: str) -> Package | None:
        """Пакет по id или None."""
        with self._lock:
            package = next((p for p in self._packages if p["id"] == pid), None)
            return copy.deepcopy(package) if package is not None else None

    def update_package(self, pid: str, **fields) -> None:
        """Обновляет поля пакета."""
        with self._lock:
            pkg = next((p for p in self._packages if p["id"] == pid), None)
            if pkg is not None:
                pkg.update(copy.deepcopy(fields))

    def get_run(self, pid: str) -> Run | None:
        """Прогон пакета или None."""
        with self._lock:
            run = self._runs.get(pid)
            return copy.deepcopy(run) if run else None

    def set_run(self, pid: str, run: Run) -> None:
        """Сохраняет прогон пакета."""
        with self._lock:
            self._runs[pid] = copy.deepcopy(run)

    def create_package(self, name: str, direction: str, staged: list[dict],
                       pid: str | None = None) -> Package:
        """Регистрирует пакет по данным формы приема.

        staged - список {"name", "type", "content"} от клиента; контроль
        формата повторяется на сервере (правила InboxScanner). Файлы
        сохраняются в каталог пакета внутри inbox.

        pid задается только тестами-сидами; очередной номер берется
        из последовательности (сбрасывается рестартом процесса -
        SQL-бэкенд переживает его).
        """
        if pid is None:
            with self._lock:
                pid = f"2026-{self._next_pkg_num:03d}"
                self._next_pkg_num += 1
        now = datetime.now()

        # номер пакета переиспользуется после перезапуска процесса -
        # содержимое прежнего одноименного каталога не должно подмешиваться
        pkg_dir = self.inbox_dir(pid)
        prepare_package_dir(pkg_dir)
        ok_files, rejected = prepare_staged(pkg_dir, staged)

        pkg = build_package(pid, name, direction, staged,
                            ok_files, rejected, now)
        with self._lock:
            # хранилище владеет своей записью; вызывающий получает pkg ниже
            self._packages.insert(0, copy.deepcopy(pkg))
        if pkg["status"] == PackageStatus.REJECT:
            log.warning("Пакет %s отклонен: %s", pid, pkg["reject_reason"])
        else:
            log.info(
                "Пакет %s принят: «%s», документов %d, карантин %d",
                pid, name, len(ok_files), len(rejected),
            )
        return pkg

    def reset(self, package: str | None = None) -> None:
        """Очистка (тесты); без аргумента - весь реестр и флаг configure."""
        with self._lock:
            if package is None:
                self._packages = []
                self._runs = {}
                self._configured = False
            else:
                self._packages = [p for p in self._packages if p["id"] != package]
                self._runs.pop(package, None)


# --- фасад над выбранным бэкендом -----------------------------------------

_fallback = InMemoryRegistry()
_lazy: LazyBackend[SeedableRunStore] = LazyBackend(
    lambda: REGISTRY_SQL.open(_fallback.inbox_root or Path("inbox")),
    lambda: _fallback,
)


def _resolve() -> SeedableRunStore:
    return _lazy.backend()


def configure(inbox_root: Path, force: bool = False) -> None:
    """Задает корень каталога inbox и загружает сиды (один раз).

    force=True переконфигурирует заново (тесты: смена tmp-каталога).
    Вызывается до первого обращения к реестру; если настроен
    DATABASE_URL, при первом обращении реестр переезжает на
    PostgreSQL с тем же корнем inbox (без сидов: демо - make seed).
    """
    global _fallback
    if not _lazy.resolved:
        if _fallback._configured and not force:
            return
        _fallback.inbox_root = inbox_root
        if force:
            _fallback.reset()
        _fallback.load_seeds()
        _fallback._configured = True
    else:
        # SQL-бэкенд уже выбран: смена корня inbox пересоздает реестр
        from services.orchestrator.registry_pg import SqlRegistry

        _lazy.use(SqlRegistry(inbox_root))


def reset_backend() -> None:
    """Сброс выбора бэкенда и конфигурации (тесты: смена DATABASE_URL)."""
    global _fallback
    _fallback = InMemoryRegistry()
    _lazy.reset()


def reset(package: str | None = None) -> None:
    """Очистка реестра (тесты), без разрешения бэкенда."""
    if _lazy.resolved:
        _lazy.backend().reset(package)
    else:
        _fallback.reset(package)


def load_seeds() -> None:
    """Сиды контрольного примера (только в пустой реестр; make seed)."""
    _resolve().load_seeds()


def inbox_dir(package: str) -> Path:
    """Каталог пакета во входящих."""
    return _resolve().inbox_dir(package)


def list_packages() -> list[Package]:
    """Все пакеты реестра."""
    return _resolve().list_packages()


def get_package(pid: str) -> Package | None:
    """Пакет по id или None."""
    return _resolve().get_package(pid)


def update_package(pid: str, **fields) -> None:
    """Обновляет поля пакета."""
    _resolve().update_package(pid, **fields)


def get_run(pid: str) -> Run | None:
    """Прогон пакета или None."""
    return _resolve().get_run(pid)


def set_run(pid: str, run: Run) -> None:
    """Сохраняет прогон пакета."""
    _resolve().set_run(pid, run)


def create_package(name: str, direction: str, staged: list[dict],
                   pid: str | None = None) -> Package:
    """Регистрирует новый пакет."""
    return _resolve().create_package(name, direction, staged, pid=pid)


def backend_name() -> str:
    """Имя бэкенда для логов и диагностики UI; разрешает бэкенд -
    стартовый лог показывает реальный режим и при холодном старте."""
    return _lazy.backend_name()
