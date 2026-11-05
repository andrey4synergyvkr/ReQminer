from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact
from contracts.stores import ChunkStore

from services.common.logging import get_logger
from services.common.progress import ProgressTick
from services.ingestor.chunker import chunk_markdown, chunk_plain
from services.ingestor.repository import chunks_repo

log = get_logger("ingestor.scanner")

# Допустимые форматы (машиночитаемые текстовые файлы): расширение -> подпись.
ALLOWED_FORMATS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".csv": "csv",
}

# Форматы, нарезаемые по структуре заголовков; остальные - по размеру.
STRUCTURED_FORMATS = {"markdown"}


@dataclass
class IngestResult:
    """Результат приема пакета: что прочитано и что попало в карантин."""

    documents: int = 0
    fragments: int = 0
    quarantine: int = 0
    rejected: list[str] = field(default_factory=list)


def _failed_artifact(package: str, path: Path) -> SourceArtifact:
    """Артефакт документа, не прошедшего прием (карантин): статус failed,
    фрагментов нет."""
    return SourceArtifact(
        id=f"{package}:{path.name}",
        file_path=str(path),
        file_name=path.name,
        total_chunks=0,
        parsing_status=ParsingStatus.FAILED,
    )


def _accept_file(
    repo: ChunkStore, package: str, path: Path, result: IngestResult
) -> None:
    """Разбирает один файл: фрагменты в Chunks или запись в карантин."""
    fmt = ALLOWED_FORMATS.get(path.suffix.lower())
    if fmt is None:
        result.quarantine += 1
        result.rejected.append(path.name)
        log.warning("Ingestor %s: документ %s в карантине (недопустимый формат)", package, path.name)
        repo.save(package, _failed_artifact(package, path), [])
        return
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result.quarantine += 1
        result.rejected.append(path.name)
        log.warning("Ingestor %s: документ %s в карантине (ошибка чтения)", package, path.name)
        repo.save(package, _failed_artifact(package, path), [])
        return

    chunker = chunk_markdown if fmt in STRUCTURED_FORMATS else chunk_plain
    chunks = chunker(path.name, content)
    # doc хранится в метаданных фрагмента - так Extractor и UI находят
    # документ-источник фрагмента
    for c in chunks:
        c.metadata_json = json.dumps({"doc": path.name})
    artifact = SourceArtifact(
        id=f"{package}:{path.name}",
        file_path=str(path),
        file_name=path.name,
        total_chunks=len(chunks),
        parsing_status=ParsingStatus.PARSED,
    )
    saved = repo.save(package, artifact, chunks)
    result.documents += 1
    result.fragments += saved
    log.debug(
        "Ingestor %s: %s — формат %s, фрагментов %d (новых %d)",
        package, path.name, fmt, len(chunks), saved,
    )


def process_package(package: str, docs_dir: Path,
                    *, chunks: ChunkStore | None = None,
                    progress: ProgressTick | None = None) -> IngestResult:
    """Читает документы пакета из каталога inbox и записывает фрагменты
    в Chunks через ChunkRepository (единственный писатель). Документ,
    не прошедший прием (недопустимый формат, ошибка чтения), получает
    артефакт со статусом failed и попадает в карантин - обработка
    пакета продолжается."""
    repo = chunks or chunks_repo
    result = IngestResult()
    if not docs_dir.is_dir():
        log.info("Ingestor %s: каталог inbox %s отсутствует — 0 документов", package, docs_dir)
        return result

    # список файлов известен до цикла: прогресс получает total и тик
    # после каждого файла, включая карантин
    paths = sorted(path for path in docs_dir.iterdir() if path.is_file())
    if progress is not None:
        progress(0, len(paths), "")
    for index, path in enumerate(paths, 1):
        _accept_file(repo, package, path, result)
        if progress is not None:
            progress(index, len(paths), path.name)
    log.info(
        "Ingestor %s: принято документов %d, фрагментов %d, карантин %d",
        package, result.documents, result.fragments, result.quarantine,
    )
    return result
