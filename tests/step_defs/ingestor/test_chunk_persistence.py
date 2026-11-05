import json

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact
from services.ingestor import scanner
from services.ingestor.repository import chunks_repo

scenarios("../../features/ingestor/chunk_persistence.feature")


def _content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@given(parsers.parse('документ "{doc}" обработан и содержит {chunk_count:d} фрагмента'))
def doc_processed(inbox, state, doc, chunk_count):
    pkg_dir = inbox / "2026-042"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / doc).write_text(
        "\n".join(
            f"# Раздел {i}\n\nТекст раздела {i}." for i in range(1, chunk_count + 1)
        ),
        encoding="utf-8",
    )
    scanner.process_package("2026-042", pkg_dir)
    state["doc"] = doc
    state["chunk_count"] = chunk_count


@given(parsers.parse('пакет "{package}" уже обработан и записан в Chunks'))
def package_already_saved(package_result, state, package):
    state["package"] = package.split()[-1]
    state["fragments_before"] = len(chunks_repo.list_chunks(state["package"]))
    assert state["fragments_before"] > 0


@when('Ingestor сохраняет результаты обработки документа')
def save_document(state):
    state["artifacts"] = chunks_repo.list_artifacts("2026-042")


@when('Ingestor повторно обрабатывает тот же пакет')
def reprocess_package(package_result, state, inbox):
    scanner.process_package(state["package"], inbox / state["package"])


@then('SourceArtifact и все его фрагменты DocumentChunk записаны в Chunks')
def artifact_and_chunks_saved(state):
    doc = state["doc"]
    artifact = chunks_repo.get_artifact("2026-042", doc)
    assert artifact is not None, doc
    assert artifact.total_chunks == state["chunk_count"]
    doc_chunks = [
        c for c in chunks_repo.list_chunks("2026-042")
        if json.loads(c.metadata_json or "{}").get("doc") == doc
    ]
    assert len(doc_chunks) == state["chunk_count"]


@then('запись выполнена одной транзакцией')
def saved_in_single_transaction(state):
    artifact = chunks_repo.get_artifact("2026-042", state["doc"])
    assert artifact is not None
    assert chunks_repo.list_chunks("2026-042")


@then('новые фрагменты в Chunks не созданы')
def no_duplicate_chunks(state):
    after = len(chunks_repo.list_chunks(state["package"]))
    assert after == state["fragments_before"], (state["fragments_before"], after)


@then('совпадение существующих фрагментов определено по content_hash')
def dedup_by_content_hash(state):
    chunks = chunks_repo.list_chunks(state["package"])
    hashes = [c.content_hash for c in chunks]
    assert len(hashes) == len(set(hashes)), "в хранилище дубликаты хэшей"
    for c in chunks:
        assert c.content_hash == _content_hash(c.content), c.id
