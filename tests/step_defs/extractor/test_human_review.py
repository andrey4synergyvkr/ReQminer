from __future__ import annotations

from extractor_steps import *  # noqa: F401,F403
from extractor_steps import PACKAGE
from pytest_bdd import given, parsers, scenarios, then, when

from services.builder import service as builder
from services.extractor.repository import knowledge_repo

scenarios("../../features/extractor/human_review.feature")

USER = "Иванов И. И."


@given(parsers.parse('создана пара-кандидат типа "{kind}" '
                     'из фактов "{a}" и "{b}"'))
def duplicate_pair_created(kind, a, b):
    added = knowledge_repo.add_pairs(PACKAGE, [{
        "kind": kind, "reason": "совпадающий смысл формулировок",
        "a": a, "b": b,
    }])
    assert added == 1


@when(parsers.parse('аналитик подтверждает факт "{fid}"'))
def analyst_confirms(fid):
    assert knowledge_repo.review_facts([fid], "confirmed", USER, PACKAGE) == 1


@when(parsers.parse('аналитик отклоняет факт "{fid}"'))
def analyst_rejects(fid):
    assert knowledge_repo.review_facts([fid], "rejected", USER, PACKAGE) == 1


@when('аналитик подтверждает дубликат в паре')
def analyst_confirms_duplicate():
    pair = knowledge_repo.pairs_of(PACKAGE)[0]
    assert knowledge_repo.review_pair(PACKAGE, pair["id"], "pair_duplicate", USER)


@then(parsers.parse('факт "{fid}" получил статус "{status}"'))
def fact_status(fid, status):
    fact = knowledge_repo.get_fact(fid, PACKAGE)
    assert fact is not None, fid
    assert fact["status"] == status, (fid, fact["status"])


@then(parsers.parse('у факта "{fid}" заполнены reviewed_by и validated_at'))
def fact_review_fields(fid):
    fact = knowledge_repo.get_fact(fid, PACKAGE)
    assert fact["reviewed_by"] == USER, fid
    assert fact["validated_at"], fid


@then(parsers.parse('факт "{fid}" не попадает в каркас Builder-а'))
def fact_not_in_skeleton(fid, outbox_root):
    fact = knowledge_repo.get_fact(fid, PACKAGE)
    docs = builder.build(PACKAGE, knowledge_repo.list_facts(PACKAGE), {})
    for text in docs.values():
        assert fact["title"] not in text, fid


@then('более уверенный факт пары получил статус "confirmed"')
def pair_winner_confirmed():
    pair = knowledge_repo.pairs_of(PACKAGE)[0]
    a = knowledge_repo.get_fact(pair["a"], PACKAGE)
    b = knowledge_repo.get_fact(pair["b"], PACKAGE)
    keep = a if (a.get("confidence") or 0) >= (b.get("confidence") or 0) else b
    assert keep["status"] == "confirmed", keep["id"]


@then('второй факт пары получил статус "duplicate"')
def pair_loser_duplicate():
    pair = knowledge_repo.pairs_of(PACKAGE)[0]
    a = knowledge_repo.get_fact(pair["a"], PACKAGE)
    b = knowledge_repo.get_fact(pair["b"], PACKAGE)
    dup = a if (a.get("confidence") or 0) < (b.get("confidence") or 0) else b
    assert dup["status"] == "duplicate", dup["id"]


@then('новые факты в Knowledge не созданы')
def no_new_facts(state):
    assert knowledge_repo.facts_total(PACKAGE) == state["facts_before"]
