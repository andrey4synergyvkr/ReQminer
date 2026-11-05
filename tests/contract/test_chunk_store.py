from __future__ import annotations

import hashlib
import json

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact

PACKAGE = "2026-810"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk(index: int, text: str, doc: str = "doc.md") -> DocumentChunk:
    return DocumentChunk(
        id=f"{PACKAGE}:{doc}:{index}",
        chunk_index=index,
        content=text,
        content_hash=_hash(text),
        start_offset=0,
        end_offset=len(text),
        token_count=len(text) // 4,
        metadata=json.dumps({"doc": doc}),
    )


def _artifact(doc: str = "doc.md", total: int = 1) -> SourceArtifact:
    return SourceArtifact(
        id=f"{PACKAGE}:{doc}",
        file_path=doc,
        file_name=doc,
        total_chunks=total,
        parsing_status=ParsingStatus.PARSED,
    )


def test_save_is_idempotent(chunk_store):
    artifact = _artifact()
    chunks = [_chunk(1, "Текст требования")]
    assert chunk_store.save(PACKAGE, artifact, chunks) == 1
    assert chunk_store.save(PACKAGE, artifact, chunks) == 0
    assert chunk_store.stats(PACKAGE) == {"documents": 1, "fragments": 1}


def test_duplicate_hashes_in_one_batch(chunk_store):
    chunks = [_chunk(1, "Повторяющийся абзац"), _chunk(2, "Повторяющийся абзац")]
    assert chunk_store.save(PACKAGE, _artifact(), chunks) == 1
    assert chunk_store.stats(PACKAGE)["fragments"] == 1


def test_same_hash_across_documents(chunk_store):
    text = "Общий boilerplate"
    assert chunk_store.save(PACKAGE, _artifact("a.md"), [_chunk(1, text, "a.md")]) == 1
    assert chunk_store.save(PACKAGE, _artifact("b.md"), [_chunk(1, text, "b.md")]) == 1

    assert chunk_store.stats(PACKAGE) == {"documents": 2, "fragments": 2}
    assert len(chunk_store.list_artifacts(PACKAGE)) == 2
    assert chunk_store.get_fragment(PACKAGE, "a.md", 1) == text
    assert chunk_store.get_fragment(PACKAGE, "b.md", 1) == text


def test_stats_matches_lists(chunk_store):
    chunk_store.save(PACKAGE, _artifact("a.md", 2), [
        _chunk(1, "Первый", "a.md"),
        _chunk(2, "Второй", "a.md"),
    ])
    chunk_store.save(PACKAGE, _artifact("b.md", 1), [_chunk(1, "Третий", "b.md")])

    assert chunk_store.stats(PACKAGE) == {
        "documents": len(chunk_store.list_artifacts(PACKAGE)),
        "fragments": len(chunk_store.list_chunks(PACKAGE)),
    }
    assert chunk_store.get_artifact(PACKAGE, "a.md").total_chunks == 2


def test_resave_updates_artifact_without_duplicate(chunk_store):
    chunk_store.save(PACKAGE, _artifact(total=1), [_chunk(1, "Старый текст")])
    chunk_store.save(PACKAGE, _artifact(total=2), [_chunk(2, "Новый текст")])

    artifacts = chunk_store.list_artifacts(PACKAGE)
    assert len(artifacts) == 1
    assert artifacts[0].total_chunks == 2
    assert len(chunk_store.list_chunks(PACKAGE)) == 1
    assert chunk_store.get_fragment(PACKAGE, "doc.md", 1) is None
    assert chunk_store.get_fragment(PACKAGE, "doc.md", 2) == "Новый текст"
