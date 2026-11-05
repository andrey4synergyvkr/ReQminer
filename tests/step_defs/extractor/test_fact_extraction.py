from __future__ import annotations

import json

from extractor_steps import *  # noqa: F401,F403
from extractor_steps import (
    FlakyCloudAdapter,
    PACKAGE,
    reset_package_fragments,
)
from pytest_bdd import given, parsers, scenarios, then

from services.common import llm_adapter as adapter_module
from services.extractor.repository import knowledge_repo

scenarios("../../features/extractor/fact_extraction.feature")

_NO_REQUIREMENT_FRAGMENTS = [
    "Команда проекта подтверждает готовность к старту работ.",
    "Протокол встречи прилагается к настоящему письму.",
]


@given(parsers.parse('фрагмент {frag:d} документа "{doc}" содержит требование о сроке внедрения'))
def fragment_with_deadline(frag, doc):
    reset_package_fragments([
        "Настоящее техническое задание определяет требования к системе.",
        "Срок внедрения системы — не позднее трёх месяцев с даты подписания договора.",
    ])


@given('LLM возвращает ошибку для первых 2 обращений')
def flaky_provider(monkeypatch):
    answer = json.dumps({
        "candidates": [{
            "type": "us",
            "title": "Как аналитик, я хочу загружать входящие документы.",
            "confidence": 0.85,
        }],
    }, ensure_ascii=False)
    monkeypatch.setattr(
        adapter_module, "_adapter", FlakyCloudAdapter(failures=2, answer=answer)
    )


@given('фрагменты пакета не содержат требований')
def fragments_without_requirements():
    reset_package_fragments(_NO_REQUIREMENT_FRAGMENTS)


@then(parsers.parse('для каждого кандидата создан факт со статусом "{status}"'))
def facts_pending_review(state, status):
    facts = knowledge_repo.list_facts(PACKAGE)
    assert facts, "факты не извлечены"
    assert all(f["status"] == status for f in facts)


@then('у каждого факта заполнены raw_snippet и confidence')
def facts_have_snippet_and_confidence():
    for f in knowledge_repo.list_facts(PACKAGE):
        assert f.get("raw_snippet"), f["id"]
        assert f.get("confidence"), f["id"]


@then('ссылка на фрагмент-источник сохранена в факте')
def facts_have_source():
    for f in knowledge_repo.list_facts(PACKAGE):
        assert f["doc"] and f["frag"], f["id"]


@then(parsers.parse('факт извлечен из документа "{doc}", фрагмент {frag:d}'))
def fact_traced_to_source(doc, frag):
    facts = [
        f for f in knowledge_repo.list_facts(PACKAGE)
        if f["doc"] == doc and f["frag"] == frag
    ]
    assert facts, (doc, frag)


@then(parsers.parse('в графе Knowledge есть ребро "извлечен из" '
                    'от факта к фрагменту-источнику'))
def graph_has_trace_edge():
    from services.web_ui.data import adapter

    graph = adapter.get_graph(PACKAGE)
    trace = [e for e in graph["edges"] if e["type"] == "извлечен из"]
    assert trace, "ребер «извлечен из» нет"


@then('извлечение пакета завершено')
def extraction_finished(state):
    assert state["result"].facts > 0


@then(parsers.parse('метрика llm_retries прогона равна {retries:d}'))
def llm_retries_metric(state, retries):
    assert state["result"].llm_retries == retries


@then('в Knowledge не создано ни одного факта')
def no_facts_created():
    assert knowledge_repo.facts_total(PACKAGE) == 0
