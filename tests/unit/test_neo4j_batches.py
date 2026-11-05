from __future__ import annotations

import os

import pytest

from services.common import graph_db
from services.extractor.repository_neo4j import Neo4jKnowledgeRepository

PACKAGE = "2026-995"


@pytest.fixture
def repo():
    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "reqminer")
    graph_db.reset_driver()
    if graph_db.get_driver() is None:
        pytest.skip("Neo4j недоступен: docker compose up -d graph")
    repository = Neo4jKnowledgeRepository()
    repository.reset(PACKAGE)
    yield repository
    repository.reset(PACKAGE)


def _fact(i: int, **extra) -> dict:
    fact = {
        "type": "us",
        "title": f"Требование {i:03d}",
        "confidence": 0.9,
        "status": "pending_review",
        "doc": "tz.md",
        "frag": i,
    }
    fact.update(extra)
    return fact


def test_ids_continue_across_batches(repo):
    first = [_fact(1), _fact(2)]
    assert repo.add_facts(PACKAGE, first) == 2
    second = [_fact(3)]
    assert repo.add_facts(PACKAGE, second) == 1
    assert [f["id"] for f in first] == ["F-001", "F-002"]
    assert second[0]["id"] == "F-003"


def test_duplicates_are_skipped_within_one_batch(repo):
    facts = [_fact(10), _fact(10)]
    assert repo.add_facts(PACKAGE, facts) == 1
    assert len(repo.list_facts(PACKAGE)) == 1


def test_repeated_batch_adds_nothing(repo):
    facts = [_fact(11), _fact(12)]
    repo.add_facts(PACKAGE, facts)
    assert repo.add_facts(PACKAGE, [_fact(11), _fact(12)]) == 0
    assert repo.facts_total(PACKAGE) == 2


def test_edges_are_batched_and_idempotent(repo):
    facts = [_fact(20), _fact(21)]
    repo.add_facts(PACKAGE, facts)
    edges = [{"source": facts[0]["id"], "target": facts[1]["id"], "type": "содержит"}]
    assert repo.add_edges(PACKAGE, edges) == 1
    assert repo.add_edges(PACKAGE, edges) == 0
    semantic = [e for e in repo.get_graph(PACKAGE)["edges"] if e["type"] == "содержит"]
    assert len(semantic) == 1


def test_pairs_get_ids_and_apply_cascade(repo):
    facts = [_fact(30, confidence=0.9), _fact(31, confidence=0.5)]
    repo.add_facts(PACKAGE, facts)
    pairs = [{"kind": "duplicate", "reason": "похожие формулировки",
              "a": facts[0]["id"], "b": facts[1]["id"]}]
    assert repo.add_pairs(PACKAGE, pairs) == 1
    assert pairs[0]["id"] == "P-1"

    statuses = {f["id"]: f["status"] for f in repo.list_facts(PACKAGE)}
    assert statuses[facts[0]["id"]] == "pending_review"
    assert statuses[facts[1]["id"]] == "duplicate"

    assert repo.add_pairs(PACKAGE, [dict(pairs[0])]) == 0
    assert len(repo.pairs_of(PACKAGE)) == 1


def test_pair_ids_continue_across_batches(repo):
    facts = [_fact(60), _fact(61), _fact(62), _fact(63)]
    repo.add_facts(PACKAGE, facts)
    first = [{"kind": "duplicate", "reason": "первая пара",
              "a": facts[0]["id"], "b": facts[1]["id"]}]
    second = [{"kind": "duplicate", "reason": "вторая пара",
               "a": facts[2]["id"], "b": facts[3]["id"]}]
    assert repo.add_pairs(PACKAGE, first) == 1
    assert repo.add_pairs(PACKAGE, second) == 1

    assert first[0]["id"] == "P-1"
    assert second[0]["id"] == "P-2"
    assert [p["id"] for p in repo.pairs_of(PACKAGE)] == ["P-1", "P-2"]


def test_contradiction_marks_both_facts(repo):
    facts = [_fact(40), _fact(41)]
    repo.add_facts(PACKAGE, facts)
    repo.add_pairs(PACKAGE, [{"kind": "contradiction", "reason": "разные сроки",
                              "a": facts[0]["id"], "b": facts[1]["id"]}])
    statuses = {f["id"]: f["status"] for f in repo.list_facts(PACKAGE)}
    assert set(statuses.values()) == {"needs_clarification"}


def test_cascade_does_not_downgrade_confirmed_fact(repo):
    facts = [_fact(42, status="confirmed"), _fact(43)]
    repo.add_facts(PACKAGE, facts)
    repo.add_pairs(PACKAGE, [{"kind": "contradiction", "reason": "разные сроки",
                              "a": facts[0]["id"], "b": facts[1]["id"]}])
    statuses = {f["id"]: f["status"] for f in repo.list_facts(PACKAGE)}
    assert statuses[facts[0]["id"]] == "confirmed"
    assert statuses[facts[1]["id"]] == "needs_clarification"


def test_review_pair_is_one_transaction_and_rejects_unknown_action(repo):
    facts = [_fact(70, confidence=0.9), _fact(71, confidence=0.5)]
    repo.add_facts(PACKAGE, facts)
    repo.add_pairs(PACKAGE, [{"kind": "duplicate", "reason": "похожие",
                              "a": facts[0]["id"], "b": facts[1]["id"]}])

    assert repo.review_pair(PACKAGE, "P-1", "pair_approve", "тест") is False
    assert repo.pairs_of(PACKAGE)[0]["status"] == "open"

    assert repo.review_pair(PACKAGE, "P-1", "pair_duplicate", "тест") is True
    statuses = {f["id"]: f["status"] for f in repo.list_facts(PACKAGE)}
    assert statuses[facts[0]["id"]] == "confirmed"
    assert statuses[facts[1]["id"]] == "duplicate"
    assert repo.pairs_of(PACKAGE)[0]["status"] == "duplicate"
    assert all(
        f["reviewed_by"] == "тест" for f in repo.list_facts(PACKAGE)
    )


def test_facts_total_matches_list(repo):
    repo.add_facts(PACKAGE, [_fact(50), _fact(51), _fact(52)])
    assert repo.facts_total(PACKAGE) == len(repo.list_facts(PACKAGE)) == 3
