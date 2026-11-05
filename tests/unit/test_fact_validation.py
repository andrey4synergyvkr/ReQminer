from __future__ import annotations

import pytest

from contracts.records import normalize_fact
from services.extractor.repository import InMemoryKnowledgeRepository


def _fact() -> dict:
    return {
        "type": "us",
        "title": "История",
        "status": "pending_review",
        "confidence": 0.9,
        "doc": "tz.md",
        "frag": 1,
    }


@pytest.mark.parametrize("missing", ["title", "type", "status"])
def test_normalize_fact_requires_fields(missing):
    fact = _fact()
    del fact[missing]
    with pytest.raises(ValueError, match=missing):
        normalize_fact(fact)


def test_store_rejects_invalid_fact_without_partial_write():
    repo = InMemoryKnowledgeRepository()

    with pytest.raises(ValueError, match="title"):
        repo.add_facts("2026-880", [{"type": "us", "status": "pending_review"}])

    assert repo.facts_total("2026-880") == 0


def test_normalize_fact_fills_confidence_and_assigns_id():
    repo = InMemoryKnowledgeRepository()
    fact = _fact()
    fact["confidence"] = None

    repo.add_facts("2026-881", [fact])

    stored = repo.get_fact("F-001", "2026-881")
    assert stored["id"].startswith("F-")
    assert stored["confidence"] == 0.5
