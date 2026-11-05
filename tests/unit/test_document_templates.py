from __future__ import annotations

from services.builder.context import FactView
from services.builder.generator import _strip_heading, generate
from services.builder.planner import TEMPLATE_SET, plan

FACT = FactView(
    id="F-001", type="us", title="История", confidence=0.9,
    status="confirmed", doc="tz.md", frag=1,
)
TERM = FactView(
    id="F-002", type="term", title="Обращение", confidence=0.8,
    status="confirmed", doc="tz.md", frag=2,
    definition="Запрос заказчика на доработку.",
)


def _render(name: str, *, facts=(), generated=None, reason="раздел пуст"):
    return TEMPLATE_SET.render(
        f"documents/{name}", title="Раздел", facts=facts,
        empty_reason=reason, generated=generated,
    )


def test_list_document_renders_heading_and_facts():
    text = _render("functional_reqs/user_stories.md.j2", facts=(FACT,))

    assert text == (
        "# Раздел\n\n"
        "- **F-001: История** (достоверность 0.9, "
        "источник: tz.md, фрагмент 1)\n"
    )


def test_glossary_document_renders_terms():
    text = _render("glossary.md.j2", facts=(TERM,))

    assert text == (
        "# Раздел\n\n## Обращение\n\nЗапрос заказчика на доработку.\n\n"
        "_Источник: tz.md, фрагмент 2 (достоверность 0.8)_\n"
    )


def test_empty_document_renders_reason():
    text = _render("glossary.md.j2", reason="термины не извлечены")

    assert text == "# Раздел\n\n_(термины не извлечены)_\n"


def test_generated_body_replaces_fact_list():
    text = _render(
        "functional_reqs/user_stories.md.j2",
        facts=(FACT,), generated="Связный текст раздела.",
    )

    assert text == "# Раздел\n\nСвязный текст раздела.\n"
    assert text.count("# Раздел") == 1


def test_strip_heading_removes_model_duplicate():
    assert _strip_heading("# Раздел\n\nТело раздела.", "Раздел") == "Тело раздела."


def test_strip_heading_keeps_body_without_heading():
    assert _strip_heading("Тело раздела.", "Раздел") == "Тело раздела."


def test_cloud_generator_wraps_body_once(monkeypatch):
    class FakeCloud:
        mode = "cloud"

        def complete(self, system: str, user: str) -> str:
            assert "Не добавляй заголовок" in user
            return "# Пользовательские истории\n\nСвязный текст."

    monkeypatch.setattr(
        "services.builder.generator.get_adapter", lambda: FakeCloud()
    )
    facts = [{
        "id": "F-005", "type": "us",
        "title": "Как аналитик, я хочу видеть список обращений",
        "confidence": 0.9, "status": "confirmed",
        "doc": "tz.md", "frag": 5,
    }]

    docs = generate(plan(facts))
    text = docs["functional_reqs/user_stories.md"]

    assert text == "# Пользовательские истории\n\nСвязный текст.\n"
    assert text.count("# Пользовательские истории") == 1
