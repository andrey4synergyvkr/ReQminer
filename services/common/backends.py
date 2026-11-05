from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from contracts.stores import SeedableChunkStore, SeedableRunStore
from services.common.lazy_backend import LazyBackend

T = TypeVar("T")


@dataclass(frozen=True)
class BackendSpec(Generic[T]):
    """Описание бэкенда: имя для диагностики и фабрика с аргументами."""

    name: str
    factory: Callable[..., T | None]

    def open(self, *args) -> T | None:
        """Открывает бэкенд; None, если зависимость недоступна."""
        return self.factory(*args)


def _sql_chunks() -> SeedableChunkStore | None:
    from services.common import db

    # импорт модуля с таблицами до init_db: модели попадают в metadata
    from services.ingestor import repository_pg

    return repository_pg.SqlChunkRepository() if db.init_db() else None


def _neo4j_knowledge():
    from services.common import graph_db

    if not graph_db.init_graph():
        return None
    from services.extractor.repository_neo4j import Neo4jKnowledgeRepository

    return Neo4jKnowledgeRepository()


def _sql_registry(inbox_root) -> SeedableRunStore | None:
    from pathlib import Path

    from services.common import db

    # импорт модуля с таблицами до init_db: модели попадают в metadata
    from services.orchestrator import registry_pg

    if db.init_db():
        return registry_pg.SqlRegistry(inbox_root or Path("inbox"))
    return None


CHUNKS_SQL: BackendSpec[SeedableChunkStore] = BackendSpec(
    "chunks-sql", _sql_chunks
)
KNOWLEDGE_NEO4J: BackendSpec = BackendSpec("knowledge-neo4j", _neo4j_knowledge)
REGISTRY_SQL: BackendSpec[SeedableRunStore] = BackendSpec(
    "registry-sql", _sql_registry
)


def lazy_backend(
    spec: BackendSpec[T],
    fallback: Callable[[], T],
    *args,
) -> LazyBackend[T]:
    """Фасад с липким выбором: бэкенд из spec или fallback."""
    return LazyBackend(lambda: spec.open(*args), fallback)
