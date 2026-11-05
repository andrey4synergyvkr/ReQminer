from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from sqlmodel import Field, Session, SQLModel, delete, select
from sqlalchemy import Column, Text, text

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact

from demo.scenario import DEMO_PACKAGE
from services.common.logging import get_logger

log = get_logger("ingestor.repository_pg")

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactRow(SQLModel, table=True):
    """Проекция SourceArtifact: package входит в ключ хранилища."""

    __tablename__ = "source_artifacts"

    seq: Optional[int] = Field(default=None, primary_key=True)
    package: str = Field(index=True)
    artifact_id: str
    file_path: str
    file_name: str = Field(index=True)
    document_version: Optional[str] = None
    commit_hash: Optional[str] = None
    language: Optional[str] = None
    total_chunks: int = 0
    parsing_status: str = ParsingStatus.PENDING.value

    def to_domain(self) -> SourceArtifact:
        """Преобразует строку таблицы в доменный артефакт."""
        return SourceArtifact(
            id=self.artifact_id,
            file_path=self.file_path,
            file_name=self.file_name,
            document_version=self.document_version,
            commit_hash=self.commit_hash,
            language=self.language,
            total_chunks=self.total_chunks,
            parsing_status=ParsingStatus(self.parsing_status),
        )


class ChunkRow(SQLModel, table=True):
    """Проекция DocumentChunk; python-атрибут metadata_json лежит в колонке
    metadata (имя атрибута metadata зарезервировано SQLAlchemy)."""

    __tablename__ = "document_chunks"

    seq: Optional[int] = Field(default=None, primary_key=True)
    package: str = Field(index=True)
    # документ-владелец: идентичность фрагмента (package, artifact_id, hash)
    artifact_id: str = ""
    chunk_id: str
    chunk_index: int = 0
    content: str
    token_count: Optional[int] = None
    start_offset: int = 0
    end_offset: int = 0
    markdown_path: Optional[str] = None
    overlap_size: Optional[int] = None
    content_hash: str = Field(index=True)
    metadata_json: Optional[str] = Field(
        default=None, sa_column=Column("metadata", Text)
    )

    def to_domain(self) -> DocumentChunk:
        """Преобразует строку таблицы в доменный фрагмент."""
        return DocumentChunk(
            id=self.chunk_id,
            chunk_index=self.chunk_index,
            content=self.content,
            token_count=self.token_count,
            start_offset=self.start_offset,
            end_offset=self.end_offset,
            markdown_path=self.markdown_path,
            overlap_size=self.overlap_size,
            content_hash=self.content_hash,
            # DocumentChunk читается по alias "metadata" (contracts/ontology.py)
            metadata=self.metadata_json,
        )


class SqlChunkRepository:
    """Хранилище Chunks на PostgreSQL: те же методы, что у in-memory.

    Артефакты лежат в source_artifacts, фрагменты - в document_chunks.
    Идентичность фрагмента задаёт уникальный индекс (package, artifact_id,
    content_hash), а seq хранит порядок записи.
    """

    def __init__(self) -> None:
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Идемпотентно добавляет artifact_id и уникальный индекс.

        Позволяет обновить существующую БД без `make db-reset`: старые
        фрагменты получают artifact_id из metadata.doc.
        """
        with self._session() as session:
            session.execute(text(
                "ALTER TABLE document_chunks "
                "ADD COLUMN IF NOT EXISTS artifact_id VARCHAR"
            ))
            session.execute(text(
                "UPDATE document_chunks "
                "SET artifact_id = package || ':' || (metadata::jsonb ->> 'doc') "
                "WHERE (artifact_id IS NULL OR artifact_id = '') "
                "AND metadata IS NOT NULL"
            ))
            session.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_chunk_artifact_hash "
                "ON document_chunks (package, artifact_id, content_hash)"
            ))
            session.commit()

    def _session(self) -> Session:
        # engine гарантированно не None: бэкенд создается только при успехе
        # подключения (db.get_engine/init_db в repository.py)
        from services.common.db import get_engine

        return Session(get_engine())

    # --- сид контрольного примера -------------------------------------------
    def seed_demo(self, package: str = DEMO_PACKAGE) -> None:
        """Загружает фрагменты пакета «Обращение 2026-042» (как in-memory)."""
        with self._session() as session:
            existing = session.exec(
                select(ChunkRow).where(ChunkRow.package == package)
            ).first()
        if existing is not None:
            return
        with open(_DATA_DIR / "fragments.json", encoding="utf-8") as f:
            demo: dict[str, dict[str, str]] = json.load(f)
        for doc, frags in demo.items():
            artifact = SourceArtifact(
                id=f"{package}:{doc}",
                file_path=doc,
                file_name=doc,
                total_chunks=len(frags),
                parsing_status=ParsingStatus.PARSED,
            )
            chunks = [
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
                for num, text in frags.items()
            ]
            self.save(package, artifact, chunks)

    # --- запись (единственный писатель) --------------------------------------
    def save(self, package: str, artifact: SourceArtifact,
             chunks: list[DocumentChunk]) -> int:
        """Записывает артефакт с фрагментами; идемпотентен по документу.

        Идентичность фрагмента - (package, artifact_id, content_hash).
        Повторное сохранение документа с изменённым содержимым заменяет
        его фрагменты; одинаковый текст в другом документе сохраняется.
        """
        with self._session() as session:
            row = session.exec(
                select(ArtifactRow).where(
                    ArtifactRow.package == package,
                    ArtifactRow.artifact_id == artifact.id,
                )
            ).first()
            if row is None:
                row = ArtifactRow(package=package, artifact_id=artifact.id)
                session.add(row)
            row.file_path = artifact.file_path
            row.file_name = artifact.file_name
            row.document_version = artifact.document_version
            row.commit_hash = artifact.commit_hash
            row.language = artifact.language
            row.total_chunks = artifact.total_chunks
            row.parsing_status = artifact.parsing_status.value

            existing = set(
                session.exec(
                    select(ChunkRow.content_hash).where(
                        ChunkRow.package == package,
                        ChunkRow.artifact_id == artifact.id,
                    )
                ).all()
            )
            new: list[DocumentChunk] = []
            seen: set[str] = set()
            for chunk in chunks:
                if chunk.content_hash in seen:
                    continue
                seen.add(chunk.content_hash)
                new.append(chunk)

            if existing == seen:
                added = 0
            else:
                session.exec(
                    delete(ChunkRow).where(
                        ChunkRow.package == package,
                        ChunkRow.artifact_id == artifact.id,
                    )
                )
                for c in new:
                    session.add(
                        ChunkRow(
                            package=package,
                            artifact_id=artifact.id,
                            chunk_id=c.id,
                            chunk_index=c.chunk_index,
                            content=c.content,
                            token_count=c.token_count,
                            start_offset=c.start_offset,
                            end_offset=c.end_offset,
                            markdown_path=c.markdown_path,
                            overlap_size=c.overlap_size,
                            content_hash=c.content_hash,
                            metadata_json=c.metadata_json,
                        )
                    )
                added = len(new)
            session.commit()
        log.info(
            "Запись в Chunks %s: артефакт %s (статус %s), фрагментов %d, новых %d, дублей %d",
            package, artifact.file_name, artifact.parsing_status.value,
            len(chunks), added, len(chunks) - added,
        )
        return added

    # --- чтение ----------------------------------------------------------------
    def list_chunks(self, package: str) -> list[DocumentChunk]:
        """Фрагменты пакета в порядке записи."""
        with self._session() as session:
            rows = session.exec(
                select(ChunkRow).where(ChunkRow.package == package)
                .order_by(ChunkRow.seq)
            ).all()
        return [r.to_domain() for r in rows]

    def list_artifacts(self, package: str) -> list[SourceArtifact]:
        """Принятые файлы пакета."""
        with self._session() as session:
            rows = session.exec(
                select(ArtifactRow).where(ArtifactRow.package == package)
                .order_by(ArtifactRow.seq)
            ).all()
        return [r.to_domain() for r in rows]

    def get_artifact(self, package: str, file_name: str) -> SourceArtifact | None:
        """Артефакт по имени файла или None."""
        with self._session() as session:
            row = session.exec(
                select(ArtifactRow).where(
                    ArtifactRow.package == package,
                    ArtifactRow.file_name == file_name,
                )
            ).first()
        return row.to_domain() if row else None

    def get_fragment(self, package: str, doc: str, frag: int) -> str | None:
        """Текст фрагмента по документу и номеру."""
        with self._session() as session:
            rows = session.exec(
                select(ChunkRow).where(
                    ChunkRow.package == package, ChunkRow.chunk_index == frag
                ).order_by(ChunkRow.seq)
            ).all()
        for r in rows:
            meta = json.loads(r.metadata_json or "{}")
            if meta.get("doc") == doc:
                return r.content
        return None

    def stats(self, package: str) -> dict:
        """Счётчики хранилища для экрана и отчёта."""
        chunks = self.list_chunks(package)
        docs = {json.loads(c.metadata_json or "{}").get("doc") for c in chunks}
        docs.discard(None)
        return {"documents": len(docs), "fragments": len(chunks)}

    def reset(self, package: str | None = None) -> None:
        """Очистка (тесты); без аргумента - все пакеты."""
        from sqlmodel import delete

        with self._session() as session:
            if package is None:
                session.exec(delete(ArtifactRow))
                session.exec(delete(ChunkRow))
            else:
                session.exec(
                    delete(ArtifactRow).where(ArtifactRow.package == package)
                )
                session.exec(
                    delete(ChunkRow).where(ChunkRow.package == package)
                )
            session.commit()
