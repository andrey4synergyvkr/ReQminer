from __future__ import annotations

PACKAGE = "2026-811"


def _fact(i: int, confidence: float = 0.9,
          status: str = "pending_review") -> dict:
    return {
        "type": "us",
        "title": f"Требование {i:03d}",
        "confidence": confidence,
        "status": status,
        "doc": "tz.md",
        "frag": i,
    }


def _pair(facts: list[dict], kind: str = "duplicate") -> dict:
    return {"kind": kind, "reason": "похожие формулировки",
            "a": facts[0]["id"], "b": facts[1]["id"]}


def test_fact_ids_continue_across_batches(knowledge_store):
    first = [_fact(1), _fact(2)]
    assert knowledge_store.add_facts(PACKAGE, first) == 2
    second = [_fact(3)]
    assert knowledge_store.add_facts(PACKAGE, second) == 1
    assert [f["id"] for f in first] == ["F-001", "F-002"]
    assert second[0]["id"] == "F-003"


def test_duplicate_facts_are_skipped(knowledge_store):
    assert knowledge_store.add_facts(PACKAGE, [_fact(1), _fact(1)]) == 1
    assert knowledge_store.facts_total(PACKAGE) == 1


def test_null_confidence_normalized(knowledge_store):
    fact = _fact(1)
    fact["confidence"] = None
    knowledge_store.add_facts(PACKAGE, [fact])
    assert knowledge_store.get_fact("F-001", PACKAGE)["confidence"] == 0.5


def test_pair_ids_continue_across_batches(knowledge_store):
    facts = [_fact(i) for i in range(1, 5)]
    knowledge_store.add_facts(PACKAGE, facts)
    assert knowledge_store.add_pairs(PACKAGE, [_pair(facts[0:2])]) == 1
    assert knowledge_store.add_pairs(PACKAGE, [_pair(facts[2:4])]) == 1
    assert [p["id"] for p in knowledge_store.pairs_of(PACKAGE)] == ["P-1", "P-2"]


def test_duplicate_cascade_keeps_winner(knowledge_store):
    facts = [_fact(1, confidence=0.9), _fact(2, confidence=0.5)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts)])

    statuses = {f["id"]: f["status"] for f in knowledge_store.list_facts(PACKAGE)}
    assert statuses["F-001"] == "pending_review"
    assert statuses["F-002"] == "duplicate"


def test_cascade_does_not_downgrade_terminal_status(knowledge_store):
    facts = [_fact(1, status="confirmed"), _fact(2)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts, kind="contradiction")])

    statuses = {f["id"]: f["status"] for f in knowledge_store.list_facts(PACKAGE)}
    assert statuses["F-001"] == "confirmed"
    assert statuses["F-002"] == "needs_clarification"


def test_review_pair_unknown_action_rejected(knowledge_store):
    facts = [_fact(1), _fact(2)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts)])

    assert knowledge_store.review_pair(PACKAGE, "P-1", "pair_approve", "тест") is False
    assert knowledge_store.pairs_of(PACKAGE)[0]["status"] == "open"


def test_review_pair_duplicate_confirms_winner(knowledge_store):
    facts = [_fact(1, confidence=0.9), _fact(2, confidence=0.5)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts)])

    assert knowledge_store.review_pair(PACKAGE, "P-1", "pair_duplicate", "тест")
    statuses = {f["id"]: f["status"] for f in knowledge_store.list_facts(PACKAGE)}
    assert statuses == {"F-001": "confirmed", "F-002": "duplicate"}
    assert knowledge_store.pairs_of(PACKAGE)[0]["status"] == "duplicate"
    assert all(
        f["reviewed_by"] == "тест"
        for f in knowledge_store.list_facts(PACKAGE)
    )


def test_review_pair_dismiss_returns_to_pending(knowledge_store):
    facts = [_fact(1), _fact(2)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts, kind="contradiction")])

    assert knowledge_store.review_pair(PACKAGE, "P-1", "pair_dismiss", "тест")
    statuses = {f["id"]: f["status"] for f in knowledge_store.list_facts(PACKAGE)}
    assert statuses == {"F-001": "pending_review", "F-002": "pending_review"}
    assert knowledge_store.pairs_of(PACKAGE)[0]["status"] == "dismiss"


def test_review_facts_is_scoped_to_package(knowledge_store):
    knowledge_store.add_facts(PACKAGE, [_fact(1)])
    assert knowledge_store.review_facts(
        ["F-001"], "confirmed", "тест", "2026-899"
    ) == 0
    assert knowledge_store.get_fact("F-001", PACKAGE)["status"] == "pending_review"


def test_pairs_have_same_shape(knowledge_store):
    facts = [_fact(1), _fact(2)]
    knowledge_store.add_facts(PACKAGE, facts)
    knowledge_store.add_pairs(PACKAGE, [_pair(facts)])

    assert set(knowledge_store.pairs_of(PACKAGE)[0]) == {
        "a", "b", "id", "kind", "reason", "status",
    }
