from __future__ import annotations

from builder_steps import *  # noqa: F401,F403
from builder_steps import make_fact
from pytest_bdd import given, parsers, scenarios, then

scenarios("../../features/builder/document_generation.feature")


@given(parsers.parse('раздел {file} содержит {count:d} пользовательских историй'))
def stories_in_section(state, file, count):
    state["facts"] = [make_fact(i, "us") for i in range(1, count + 1)]


@then('текст раздела собран из фактов раздела')
def generated_from_facts(state):
    text = state["docs"]["functional_reqs/user_stories.md"]
    assert text.startswith("# Пользовательские истории\n")
    for fact in state["facts"]:
        assert fact["title"] in text, fact["id"]


@then('в тексте раздела сохранена трассировка фактов на источники')
def traceability(state):
    text = state["docs"]["functional_reqs/user_stories.md"]
    for fact in state["facts"]:
        assert fact["doc"] in text, fact["id"]
        assert f"фрагмент {fact['frag']}" in text, fact["id"]


@then('глоссарий заполнен шаблоном-заглушкой')
def glossary_stub(state):
    assert "раздел пуст" in state["docs"]["glossary.md"]


@then('глоссарий не содержит извлеченных фактов')
def no_glossary_facts(state):
    assert "Требование" not in state["docs"]["glossary.md"]
