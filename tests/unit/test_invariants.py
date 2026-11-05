from __future__ import annotations

from contracts.pair_rules import detector_cascade
from services.builder import service as builder
from services.extractor.repository import (
    InMemoryKnowledgeRepository,
    knowledge_repo,
)
from services.ingestor import scanner
from services.orchestrator.registry import InMemoryRegistry

PACKAGE = "2026-840"


def _fact(title: str = "История", i: int = 1) -> dict:
    return {
        "type": "us",
        "title": title,
        "confidence": 0.9,
        "status": "confirmed",
        "doc": "tz.md",
        "frag": i,
    }


def test_builder_does_not_write_knowledge(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTBOX_ROOT", str(tmp_path / "outbox"))
    knowledge_repo.add_facts(PACKAGE, [_fact()])
    before = [dict(fact) for fact in knowledge_repo.list_facts(PACKAGE)]

    builder.build(PACKAGE, knowledge_repo.list_facts(PACKAGE), {
        "documents": 1, "fragments": 1, "facts": 1,
    })

    after = [dict(fact) for fact in knowledge_repo.list_facts(PACKAGE)]
    assert after == before


def test_scanner_does_not_write_knowledge(tmp_path):
    inbox = tmp_path / PACKAGE
    inbox.mkdir()
    (inbox / "tz.md").write_text("# Требования\n\nТекст.\n", encoding="utf-8")

    scanner.process_package(PACKAGE, inbox)

    assert knowledge_repo.facts_total(PACKAGE) == 0


def test_fact_ids_are_unique_within_package():
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [_fact("Первое", 1), _fact("Второе", 2)])
    repo.add_facts(PACKAGE, [_fact("Третье", 3)])

    ids = [fact["id"] for fact in repo.list_facts(PACKAGE)]
    assert ids == ["F-001", "F-002", "F-003"]
    assert len(ids) == len(set(ids))

    repo.add_facts("2026-841", [_fact("Другое", 1)])
    assert repo.get_fact("F-001", "2026-841")["title"] == "Другое"


def test_detector_does_not_downgrade_terminal_status():
    changes = detector_cascade(
        "contradiction",
        {"id": "F-001", "status": "confirmed", "confidence": 0.9},
        {"id": "F-002", "status": "pending_review", "confidence": 0.5},
    )
    assert changes == {"F-002": "needs_clarification"}


def test_new_registry_is_empty():
    registry = InMemoryRegistry()
    assert registry.list_packages() == []
    assert registry.get_run(PACKAGE) is None
