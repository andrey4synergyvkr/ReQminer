from __future__ import annotations

from services.extractor.repository import InMemoryKnowledgeRepository

PACKAGE = "2026-701"
OTHER = "2026-702"


def _fact(title: str, confidence=0.9, status="pending_review") -> dict:
    return {
        "type": "us",
        "title": title,
        "confidence": confidence,
        "status": status,
        "doc": "tz.md",
        "frag": 1,
    }


def test_get_fact_is_scoped_to_package():
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [_fact("Требование")])

    assert repo.get_fact("F-001", PACKAGE) is not None
    assert repo.get_fact("F-001", OTHER) is None


def test_review_facts_with_unknown_package_changes_nothing():
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [_fact("Требование")])
    repo.add_facts(OTHER, [_fact("Другое требование")])
    assert repo.review_facts(["F-001"], "confirmed", "тест", "2026-799") == 0
    assert repo.get_fact("F-001", PACKAGE)["status"] == "pending_review"
    assert repo.get_fact("F-001", OTHER)["status"] == "pending_review"


def test_null_confidence_normalized_on_write():
    repo = InMemoryKnowledgeRepository()
    fact = _fact("Без оценки")
    fact["confidence"] = None
    repo.add_facts(PACKAGE, [fact])

    assert repo.get_fact("F-001", PACKAGE)["confidence"] == 0.5


def test_unknown_pair_action_is_rejected():
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [_fact("Требование один"), _fact("Требование два")])
    repo.add_pairs(PACKAGE, [{"kind": "duplicate", "reason": "похоже",
                              "a": "F-001", "b": "F-002"}])

    assert repo.review_pair(PACKAGE, "P-1", "pair_approve", "тест") is False
    assert repo.pairs_of(PACKAGE)[0]["status"] == "open"


def test_detector_cascade_keeps_confirmed_fact():
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [
        _fact("Подтверждённое", status="confirmed"),
        _fact("Ожидает"),
    ])
    repo.add_pairs(PACKAGE, [{"kind": "contradiction", "reason": "разные сроки",
                              "a": "F-001", "b": "F-002"}])

    assert repo.get_fact("F-001", PACKAGE)["status"] == "confirmed"
    assert repo.get_fact("F-002", PACKAGE)["status"] == "needs_clarification"
