from __future__ import annotations

from builder_steps import *  # noqa: F401,F403
from pytest_bdd import parsers, scenarios, then

from services.builder.planner import TYPE_TO_FILE

scenarios("../../features/builder/skeleton_layout.feature")

_FILE_BY_TYPE = {
    "epic": "functional_reqs/epics.md",
    "feature": "functional_reqs/features.md",
    "us": "functional_reqs/user_stories.md",
}


@then('эпики, фичи и пользовательские истории записаны в разделы functional_reqs')
def functional_reqs_layout(state):
    for fact in state["facts"]:
        if fact["type"] in _FILE_BY_TYPE:
            text = state["docs"][_FILE_BY_TYPE[fact["type"]]]
            assert fact["title"] in text, fact["id"]


@then('цели качества записаны в раздел non_functional_reqs')
def nfr_layout(state):
    text = state["docs"]["non_functional_reqs/quality_goals.md"]
    for fact in state["facts"]:
        if fact["type"] == "nfr":
            assert fact["title"] in text, fact["id"]


@then('ограничения записаны в раздел constraints')
def constraints_layout(state):
    text = state["docs"]["constraints.md"]
    for fact in state["facts"]:
        if fact["type"] == "constraint":
            assert fact["title"] in text, fact["id"]


@then('термины записаны в глоссарий')
def terms_layout(state):
    text = state["docs"]["glossary.md"]
    for fact in state["facts"]:
        if fact["type"] == "term":
            assert fact["title"] in text, fact["id"]


@then('каждый факт входит ровно в один раздел каркаса')
def exactly_one_section(state):
    for fact in state["facts"]:
        hits = [
            rel for rel, text in state["docs"].items()
            if rel != "analysis_report.md" and fact["title"] in text
        ]
        assert len(hits) == 1, (fact["id"], hits)


@then('в тексте раздела у факта указаны confidence и ссылка на источник')
def trace_in_text(state):
    for fact in state["facts"]:
        text = state["docs"][TYPE_TO_FILE[fact["type"]]]
        assert str(fact["confidence"]) in text, fact["id"]
        assert fact["doc"] in text, fact["id"]
        assert f"фрагмент {fact['frag']}" in text, fact["id"]


@then(parsers.parse('глоссарий содержит заглушку "{text}"'))
def glossary_stub(state, text):
    assert text in state["docs"]["glossary.md"]


@then('остальные разделы каркаса заполнены')
def other_sections_filled(state):
    for rel, text in state["docs"].items():
        if rel not in ("glossary.md", "analysis_report.md"):
            assert "не извлечены" not in text, rel


@then('факты разложены по разделам одинаково')
def same_layout(state):
    assert state["first_docs"] == state["docs"]
