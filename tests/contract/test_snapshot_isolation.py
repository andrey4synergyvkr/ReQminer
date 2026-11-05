from __future__ import annotations

import hashlib
import json

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact

PACKAGE = "2026-830"


def _fact(i: int = 1) -> dict:
    return {
        "type": "us",
        "title": f"Требование {i:03d}",
        "confidence": 0.9,
        "status": "pending_review",
        "doc": "tz.md",
        "frag": i,
    }


def test_input_mutation_after_write_does_not_change_store(knowledge_store):
    facts = [_fact(1), _fact(2)]
    knowledge_store.add_facts(PACKAGE, facts)
    pair = {"kind": "duplicate", "reason": "похожие",
            "a": "F-001", "b": "F-002"}
    knowledge_store.add_pairs(PACKAGE, [pair])

    facts[0]["status"] = "rejected"
    facts[0]["title"] = "Изменено снаружи"
    pair["status"] = "dismiss"

    stored = knowledge_store.get_fact("F-001", PACKAGE)
    assert stored["status"] == "pending_review"
    assert stored["title"] == "Требование 001"
    assert knowledge_store.pairs_of(PACKAGE)[0]["status"] == "open"


def test_knowledge_snapshots_are_copies(knowledge_store):
    knowledge_store.add_facts(PACKAGE, [_fact(1), _fact(2)])
    knowledge_store.add_pairs(PACKAGE, [{
        "kind": "duplicate", "reason": "похожие",
        "a": "F-001", "b": "F-002",
    }])

    fact = knowledge_store.get_fact("F-001", PACKAGE)
    fact["status"] = "rejected"
    assert knowledge_store.get_fact("F-001", PACKAGE)["status"] == "pending_review"

    facts = knowledge_store.list_facts(PACKAGE)
    facts[0]["title"] = "Изменено снаружи"
    assert knowledge_store.list_facts(PACKAGE)[0]["title"] != "Изменено снаружи"

    pair = knowledge_store.pairs_of(PACKAGE)[0]
    pair["status"] = "dismiss"
    assert knowledge_store.pairs_of(PACKAGE)[0]["status"] == "open"


def test_chunk_snapshots_are_copies(chunk_store):
    text = "Текст фрагмента"
    chunk = DocumentChunk(
        id=f"{PACKAGE}:doc.md:1",
        chunk_index=1,
        content=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        start_offset=0,
        end_offset=len(text),
        token_count=len(text) // 4,
        metadata=json.dumps({"doc": "doc.md"}),
    )
    artifact = SourceArtifact(
        id=f"{PACKAGE}:doc.md",
        file_path="doc.md",
        file_name="doc.md",
        total_chunks=1,
        parsing_status=ParsingStatus.PARSED,
    )
    chunk_store.save(PACKAGE, artifact, [chunk])

    chunk.content = "Изменено после save"
    artifact.total_chunks = 99
    assert chunk_store.get_fragment(PACKAGE, "doc.md", 1) == text
    assert chunk_store.get_artifact(PACKAGE, "doc.md").total_chunks == 1

    chunks = chunk_store.list_chunks(PACKAGE)
    chunks[0].content = "Изменено снаружи"
    assert chunk_store.get_fragment(PACKAGE, "doc.md", 1) == text

    artifacts = chunk_store.list_artifacts(PACKAGE)
    artifacts[0].total_chunks = 99
    assert chunk_store.get_artifact(PACKAGE, "doc.md").total_chunks == 1


def test_registry_snapshots_are_copies(run_store):
    created = run_store.create_package(
        "Пакет", "обращение заказчика",
        [{"name": "tz.md", "type": "не определен", "content": b"# T\n"}],
        pid=PACKAGE,
    )
    created["files"][0]["verdict"] = "reject"
    assert run_store.get_package(PACKAGE)["files"][0]["verdict"] == "ok"

    pkg = run_store.get_package(PACKAGE)
    pkg["files"][0]["verdict"] = "reject"
    assert run_store.get_package(PACKAGE)["files"][0]["verdict"] == "ok"

    run = {
        "state": "done",
        "started": "2026-10-31T10:00:00",
        "finished": "31.10.2026 10:05",
        "stages": [
            {"service": "Ingestor", "mod": "нарезка", "status": "done",
             "processed": "1 документ"},
        ],
        "metrics": {"facts": 1},
    }
    run_store.set_run(PACKAGE, run)

    fetched = run_store.get_run(PACKAGE)
    fetched["stages"][0]["status"] = "failed"
    fetched["metrics"]["facts"] = 999
    stored = run_store.get_run(PACKAGE)
    assert stored["stages"][0]["status"] == "done"
    assert stored["metrics"]["facts"] == 1
