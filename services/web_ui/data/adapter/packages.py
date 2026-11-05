from __future__ import annotations

from contracts.workflow import PackageStatus

from .context import UiServices, get_services


# Кнопка «Анализ» формы приёма пакета (рис. 2.11) - отправка POST /packages.
def create_package(name: str, direction: str, staged: list[dict], *,
                   services: UiServices | None = None) -> dict:
    """Регистрирует пакет и запускает фоновый прогон (Orchestrator)."""
    services = services or get_services()
    pkg = services.registry.create_package(name, direction, staged)
    if pkg["status"] != PackageStatus.REJECT:
        services.scheduler.submit(pkg["id"])
    return pkg


# Кнопка «Анализ» в подвале реестра пакетов (рис. 2.10, выделенная строка).
# Возвращает False, если прогон уже выполняется (планировщик отклонил).
def start_analysis(pid: str, *, services: UiServices | None = None) -> bool:
    """Кнопка «Анализ» в реестре: фоновый прогон пакета."""
    services = services or get_services()
    return services.scheduler.submit(pid)
