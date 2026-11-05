from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UiServices:
    """Зависимости UI: реестр, планировщик, builder и хранилища."""

    registry: Any
    scheduler: Any
    builder: Any
    chunks: Any
    knowledge: Any


_services: UiServices | None = None


def build_default_services() -> UiServices:
    """Собирает зависимости из глобальных фасадов (композиция по умолчанию)."""
    from services.builder import service as builder
    from services.extractor.repository import knowledge_repo
    from services.ingestor.repository import chunks_repo
    from services.orchestrator import registry, scheduler

    return UiServices(
        registry=registry,
        scheduler=scheduler,
        builder=builder,
        chunks=chunks_repo,
        knowledge=knowledge_repo,
    )


def configure_services(services: UiServices) -> None:
    """Задаёт зависимости UI (startup, тесты)."""
    global _services
    _services = services


def get_services() -> UiServices:
    """Текущие зависимости; при отсутствии - композиция по умолчанию."""
    global _services
    if _services is None:
        _services = build_default_services()
    return _services


def reset_services() -> None:
    """Сброс композиции (тесты)."""
    global _services
    _services = None
