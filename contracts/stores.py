from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from contracts.ontology import DocumentChunk, SourceArtifact
from contracts.records import Fact, Graph, Package, Pair, Run


@runtime_checkable
class ChunkStore(Protocol):
    """Единственный писатель в хранилище Chunks (production-контракт)."""

    def save(
        self,
        package: str,
        artifact: SourceArtifact,
        chunks: list[DocumentChunk],
    ) -> int:
        """Сохраняет артефакт и его фрагменты; возвращает число фрагментов."""
        ...

    def list_chunks(self, package: str) -> list[DocumentChunk]:
        """Фрагменты пакета в порядке следования."""
        ...

    def list_artifacts(self, package: str) -> list[SourceArtifact]:
        """Принятые файлы пакета."""
        ...

    def get_artifact(self, package: str, file_name: str) -> SourceArtifact | None:
        """Артефакт по имени файла или None."""
        ...

    def get_fragment(self, package: str, doc: str, frag: int) -> str | None:
        """Текст фрагмента по документу и номеру."""
        ...

    def stats(self, package: str) -> dict:
        """Счётчики хранилища для экрана и отчёта."""
        ...

    def reset(self, package: str | None = None) -> None:
        """Удаляет данные пакета или всего хранилища."""
        ...


@runtime_checkable
class SeedableChunkStore(ChunkStore, Protocol):
    """Демо-порт Chunks: сид контрольного примера (не нужен production-клиентам)."""

    def seed_demo(self, package: str = ...) -> None:
        """Загружает демонстрационный пакет."""
        ...


@runtime_checkable
class KnowledgeStore(Protocol):
    """Единственный писатель в хранилище Knowledge."""

    def reset(self, package: str | None = None) -> None:
        """Удаляет знания пакета или всего хранилища."""
        ...

    def add_facts(self, package: str, facts: list[Fact]) -> int:
        """Сохраняет факты; возвращает число добавленных."""
        ...

    def add_pairs(self, package: str, pairs: list[Pair]) -> int:
        """Сохраняет пары и применяет каскад статусов."""
        ...

    def add_edges(self, package: str, edges: list[dict]) -> int:
        """Сохраняет семантические связи между фактами."""
        ...

    def list_facts(self, package: str) -> list[Fact]:
        """Факты пакета."""
        ...

    def get_fact(self, fid: str, package: str) -> Fact | None:
        """Факт по id или None."""
        ...

    def pairs_of(self, package: str) -> list[Pair]:
        """Пары пакета."""
        ...

    def facts_total(self, package: str) -> int:
        """Число фактов пакета."""
        ...

    def count_by_status(self, package: str, status: str) -> int:
        """Число фактов с указанным статусом."""
        ...

    def pending_count(self, package: str) -> int:
        """Число фактов, ждущих проверки аналитиком."""
        ...

    def review_facts(
        self,
        ids: list[str],
        new_status: str,
        user: str,
        package: str,
    ) -> int:
        """Переводит факты в новый статус; возвращает число изменённых."""
        ...

    def review_pair(
        self,
        package: str,
        pair_id: str,
        action: str,
        user: str,
    ) -> bool:
        """Применяет решение аналитика к паре."""
        ...

    def get_graph(self, package: str) -> Graph:
        """Проекция знаний пакета в граф."""
        ...


@runtime_checkable
class RunStore(Protocol):
    """Реестр пакетов и прогонов (production-контракт)."""

    def inbox_dir(self, package: str) -> Path:
        """Каталог пакета во входящих."""
        ...

    def list_packages(self) -> list[Package]:
        """Все пакеты реестра."""
        ...

    def get_package(self, pid: str) -> Package | None:
        """Пакет по id или None."""
        ...

    def update_package(self, pid: str, **fields) -> None:
        """Обновляет поля пакета."""
        ...

    def get_run(self, pid: str) -> Run | None:
        """Прогон пакета или None."""
        ...

    def set_run(self, pid: str, run: Run) -> None:
        """Сохраняет прогон пакета."""
        ...

    def create_package(
        self,
        name: str,
        direction: str,
        staged: list[dict],
        pid: str | None = None,
    ) -> Package:
        """Регистрирует новый пакет."""
        ...

    def reset(self, package: str | None = None) -> None:
        """Удаляет пакеты и прогоны."""
        ...


@runtime_checkable
class SeedableRunStore(RunStore, Protocol):
    """Демо-порт реестра: сиды контрольного примера (make seed)."""

    def load_seeds(self) -> None:
        """Загружает демонстрационные пакеты."""
        ...
