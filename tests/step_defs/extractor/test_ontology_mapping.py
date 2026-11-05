from __future__ import annotations

from extractor_steps import *  # noqa: F401,F403
from extractor_steps import PACKAGE, ScriptedAdapter, reset_package_fragments
from pytest_bdd import given, parsers, scenarios, then

from services.common import llm_adapter as adapter_module
from services.extractor.mapper import TYPE_TO_CLASS
from services.extractor.repository import knowledge_repo

scenarios("../../features/extractor/ontology_mapping.feature")

_CLASS_TO_TYPE = {cls: key for key, cls in TYPE_TO_CLASS.items()}
_CLASS_TO_TYPE["Constraint"] = "constraint"

_SEMANTIC_FRAGMENTS = [
    "Ключевая цель — хранение требований заказчика в единой системе.",
    "Функциональность «Загрузка документов»: выгрузка файлов на сервер.",
    "Эпик — крупная функциональная цель, объединяющая несколько функций системы.",
    "Как аналитик, я хочу видеть список эпик проекта.",
]


@given('LLM извлек кандидатов разных типов')
def candidates_of_types():
    reset_package_fragments([
        "Как аналитик, я хочу загружать входящие документы.",
        "Время отклика интерфейса не должно превышать двух секунд.",
        "Срок внедрения системы — не позднее трёх месяцев с даты договора.",
    ])


@given(parsers.parse('извлечены эпик "{epic}" и фича "{feature}"'))
def epic_and_feature_extracted(epic, feature):
    reset_package_fragments(_SEMANTIC_FRAGMENTS)


@given('LLM вернул кандидата без типа онтологии')
def unknown_candidate(monkeypatch):
    monkeypatch.setattr(
        adapter_module, "_adapter",
        ScriptedAdapter(unknown_candidate={
            "type": "risk", "title": "Риск срыва сроков поставки", "confidence": 0.7,
        }),
    )


@then(parsers.parse('факт "{fid}" имеет тип "{cls}"'))
def fact_has_type(fid, cls):
    fact = knowledge_repo.get_fact(fid, PACKAGE)
    assert fact is not None, fid
    assert fact["type"] == _CLASS_TO_TYPE[cls], (fid, fact["type"], cls)


@then('в графе Knowledge есть ребро "содержит" от эпика к фиче')
def graph_has_contains_edge():
    graph = knowledge_repo.get_graph(PACKAGE)
    facts = {f["id"]: f for f in knowledge_repo.list_facts(PACKAGE)}
    contains = [
        e for e in graph["edges"]
        if e["type"] == "содержит"
        and facts[e["source"]]["type"] == "epic"
        and facts[e["target"]]["type"] == "feature"
    ]
    assert contains, "ребро «содержит» от эпика к фиче не найдено"


@then('в графе Knowledge есть ребро "использует термин" '
      'от факта к термину глоссария')
def graph_has_term_edge():
    graph = knowledge_repo.get_graph(PACKAGE)
    facts = {f["id"]: f for f in knowledge_repo.list_facts(PACKAGE)}
    term_edges = [
        e for e in graph["edges"]
        if e["type"] == "использует термин"
        and facts[e["source"]]["type"] != "term"
        and facts[e["target"]]["type"] == "term"
    ]
    assert term_edges, "ребро «использует термин» не найдено"


@then('кандидат без типа не записан в Knowledge')
def unknown_candidate_discarded():
    assert knowledge_repo.facts_total(PACKAGE) == 0
