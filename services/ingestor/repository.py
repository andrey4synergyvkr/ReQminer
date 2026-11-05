from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact
from contracts.stores import SeedableChunkStore

from demo.scenario import DEMO_PACKAGE
from services.common.backends import CHUNKS_SQL, lazy_backend
from services.common.logging import get_logger

log = get_logger("ingestor.repository")

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_doc(chunk: DocumentChunk) -> str | None:
    """Документ-владелец фрагмента: метаданные или id package:doc:n."""
    try:
        doc = json.loads(chunk.metadata_json or "{}").get("doc")
    except ValueError:
        doc = None
    if doc:
        return doc
    parts = chunk.id.split(":")
    return parts[1] if len(parts) > 1 else None


class InMemoryChunkRepository:
    """In-memory хранилище фрагментов {package: [DocumentChunk]}
    и артефактов документов {package: [SourceArtifact]}.

    Запись идёт из фонового потока прогона, чтение - из потоков UI:
    методы защищены RLock, чтение отдает копии списков.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, list[DocumentChunk]] = {}
        self._artifacts: dict[str, list[SourceArtifact]] = {}
        self._lock = threading.RLock()

    # --- сид контрольного примера -----------------------------------------
    def seed_demo(self, package: str = DEMO_PACKAGE) -> None:
        """Загружает демонстрационный пакет из fixture-сида.

        Сид нужен для демо-режима без внешних СУБД; в рабочем режиме
        фрагменты приходят из process_package при загрузке пакета.
        """
        with self._lock:
            if package in self._chunks:
                return
            with open(_DATA_DIR / "fragments.json", encoding="utf-8") as f:
                demo: dict[str, dict[str, str]] = json.load(f)
            chunks: list[DocumentChunk] = []
            for doc, frags in demo.items():
                artifact = SourceArtifact(
                    id=f"{package}:{doc}",
                    file_path=doc,
                    file_name=doc,
                    total_chunks=len(frags),
                    parsing_status=ParsingStatus.PARSED,
                )
                self._artifacts.setdefault(package, []).append(artifact)
                for num, text in frags.items():
                    chunks.append(
                        DocumentChunk(
                            id=f"{package}:{doc}:{num}",
                            chunk_index=int(num),
                            content=text,
                            content_hash=_hash(text),
                            start_offset=0,
                            end_offset=len(text),
                            token_count=len(text) // 4,
                            metadata=json.dumps({"doc": doc}),
                        )
                    )
            self._chunks[package] = chunks

    # --- запись (единственный писатель) -------------------------------------
    def save(self, package: str, artifact: SourceArtifact,
             chunks: list[DocumentChunk]) -> int:
        """Записывает артефакт с фрагментами; идемпотентно по документу.

        Идентичность фрагмента - (package, документ, content_hash).
        Повторное сохранение того же документа с изменённым содержимым
        заменяет его фрагменты, а не копит старые версии.
        """
        with self._lock:
            bucket = self._chunks.setdefault(package, [])

            # дедуп внутри пачки: две одинаковые секции одного документа - один
            # фрагмент; одинаковый текст в другом документе - отдельный
            new: list[DocumentChunk] = []
            seen: set[str] = set()
            for chunk in chunks:
                if chunk.content_hash in seen:
                    continue
                seen.add(chunk.content_hash)
                # хранилище владеет своими объектами: внешняя мутация после
                # save() не должна менять сохранённые фрагменты
                new.append(chunk.model_copy(deep=True))

            existing = [
                c for c in bucket if _chunk_doc(c) == artifact.file_name
            ]
            existing_hashes = {c.content_hash for c in existing}

            # артефакт - upsert по (package, artifact_id)
            artifacts = self._artifacts.setdefault(package, [])
            stored = artifact.model_copy(deep=True)
            for i, a in enumerate(artifacts):
                if a.id == artifact.id:
                    artifacts[i] = stored
                    break
            else:
                artifacts.append(stored)

            if existing_hashes == seen:
                # содержимое документа не изменилось: фрагменты не трогаем
                added = 0
            else:
                bucket[:] = [
                    c for c in bucket if _chunk_doc(c) != artifact.file_name
                ]
                bucket.extend(new)
                added = len(new)
        log.info(
            "Запись в Chunks %s: артефакт %s (статус %s), фрагментов %d, новых %d, дублей %d",
            package, artifact.file_name, artifact.parsing_status.value,
            len(chunks), added, len(chunks) - added,
        )
        return added

    # --- чтение -------------------------------------------------------------
    def list_chunks(self, package: str) -> list[DocumentChunk]:
        """Фрагменты пакета в порядке записи."""
        with self._lock:
            return [
                chunk.model_copy(deep=True)
                for chunk in self._chunks.get(package, [])
            ]

    def list_artifacts(self, package: str) -> list[SourceArtifact]:
        """Принятые файлы пакета."""
        with self._lock:
            return [
                artifact.model_copy(deep=True)
                for artifact in self._artifacts.get(package, [])
            ]

    def get_artifact(self, package: str, file_name: str) -> SourceArtifact | None:
        """Артефакт по имени файла или None."""
        with self._lock:
            artifact = next(
                (a for a in self._artifacts.get(package, []) if a.file_name == file_name),
                None,
            )
            return artifact.model_copy(deep=True) if artifact is not None else None

    def get_fragment(self, package: str, doc: str, frag: int) -> str | None:
        """Текст фрагмента по документу и номеру."""
        with self._lock:
            for c in self._chunks.get(package, []):
                meta = json.loads(c.metadata_json or "{}")
                if meta.get("doc") == doc and c.chunk_index == frag:
                    return c.content
            return None

    def stats(self, package: str) -> dict:
        """Счётчики хранилища для экрана и отчёта."""
        with self._lock:
            chunks = list(self._chunks.get(package, []))
        docs = {json.loads(c.metadata_json or "{}").get("doc") for c in chunks}
        docs.discard(None)
        return {"documents": len(docs), "fragments": len(chunks)}

    def reset(self, package: str | None = None) -> None:
        """Очистка (приемочные тесты); без аргумента - все пакеты."""
        with self._lock:
            if package is None:
                self._chunks.clear()
                self._artifacts.clear()
            else:
                self._chunks.pop(package, None)
                self._artifacts.pop(package, None)


class _ChunkRepositoryFacade:
    """Ленивый выбор бэкенда: PostgreSQL при DATABASE_URL, иначе in-memory.

    Решение принимается один раз (LazyBackend) и не меняется до
    reset_backend: недоступная СУБД не переключает хранилище посреди
    прогона и не платит connect-таймаут на каждом вызове.
    """

    def __init__(self) -> None:
        self._fallback = InMemoryChunkRepository()
        self._lazy = lazy_backend(CHUNKS_SQL, lambda: self._fallback)

    def reset_backend(self) -> None:
        """Сброс выбора бэкенда (тесты: смена DATABASE_URL)."""
        self._fallback = InMemoryChunkRepository()
        self._lazy.reset()

    def reset(self, package: str | None = None) -> None:
        """Очистка без разрешения бэкенда: тесты не платят пробу СУБД."""
        if self._lazy.resolved:
            self._lazy.backend().reset(package)
        else:
            self._fallback.reset(package)

    def backend_name(self) -> str:
        """Имя бэкенда для логов и диагностики UI."""
        return self._lazy.backend_name()

    def _resolve(self) -> SeedableChunkStore:
        return self._lazy.backend()

    def __getattr__(self, name: str):
        return getattr(self._lazy.backend(), name)


# Единственный писатель в Chunks: фасад над выбранным бэкендом.
chunks_repo = _ChunkRepositoryFacade()
