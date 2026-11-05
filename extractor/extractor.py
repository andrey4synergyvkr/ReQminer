from __future__ import annotations

import json
import threading

from contracts.stores import ChunkStore
from services.common import parallel
from services.common.llm_adapter import get_adapter
from services.common.progress import ProgressTick
from services.ingestor.repository import chunks_repo


def _source(chunk) -> tuple[str, int]:
    """Документ и номер фрагмента-источника для трассировки."""
    try:
        doc = json.loads(chunk.metadata_json or "{}").get("doc")
    except ValueError:
        doc = None
    if not doc:
        doc = chunk.id.split(":")[1] if ":" in chunk.id else chunk.id
    return doc, chunk.chunk_index


def _chunk_candidates(adapter, package: str, chunk) -> list[dict]:
    """Кандидаты одного фрагмента с трассировкой на источник."""
    doc, frag = _source(chunk)
    return [
        {
            **cand,
            "doc": doc,
            "frag": frag,
            "package": package,
            "raw_snippet": chunk.content[:200],
        }
        for cand in adapter.extract_candidates(chunk.content)
    ]


def run(package: str, *, chunks: ChunkStore | None = None,
        adapter=None, progress: ProgressTick | None = None) -> tuple[int, list[dict]]:
    """Извлекает кандидатов из всех фрагментов пакета.

    Возвращает число фрагментов и список кандидатов. Источник фрагментов
    и адаптер можно передать явно. progress получает счётчик обработанных
    фрагментов и имя текущего документа.
    """
    llm = adapter or get_adapter()
    repo = chunks or chunks_repo
    fragments = repo.list_chunks(package)
    total = len(fragments)
    if progress is not None:
        progress(0, total, "")

    done = 0
    lock = threading.Lock()

    def on_done(chunk) -> None:
        nonlocal done
        if progress is None:
            return
        with lock:
            done += 1
            current = done
        doc, _ = _source(chunk)
        progress(current, total, doc)

    batches = parallel.map_calls(
        llm, lambda chunk: _chunk_candidates(llm, package, chunk),
        fragments, on_done=on_done,
    )
    candidates = [cand for batch in batches for cand in batch]
    return total, candidates
