from __future__ import annotations

from services.builder.prompts import BuilderPromptSet, builder_prompts

FACTS = [
    {
        "id": "F-001",
        "title": "Экспорт отчета в XLSX",
        "confidence": 0.9,
        "doc": "tz.md",
        "frag": 1,
    },
    {
        "id": "F-002",
        "title": "Срок внедрения",
        "confidence": 0.8,
        "doc": "correspondence.md",
        "frag": 3,
        "definition": "не позднее трёх месяцев",
        "acceptance": "срок соблюден",
    },
]


def test_section_prompt_contains_title_and_facts():
    prompt = BuilderPromptSet().section("Ограничения", FACTS)

    assert prompt.name == "section"
    assert "Раздел документации: «Ограничения»." in prompt.user
    assert "- [F-001] Экспорт отчета в XLSX — достоверность 0.9, " \
           "источник: tz.md, фрагмент 1" in prompt.user
    assert "- [F-002] Срок внедрения — достоверность 0.8, " \
           "источник: correspondence.md, фрагмент 3" in prompt.user


def test_section_prompt_forbids_duplicate_heading():
    prompt = BuilderPromptSet().section("Ограничения", FACTS)

    assert "Не добавляй заголовок" in prompt.user
    assert "его подставит шаблон документа" in prompt.user


def test_section_prompt_appends_definition_and_acceptance():
    prompt = BuilderPromptSet().section("Ограничения", FACTS)

    assert ". Определение: не позднее трёх месяцев" in prompt.user
    assert ". Критерий приемки: срок соблюден" in prompt.user


def test_version_matches_resource_set():
    prompts = BuilderPromptSet()

    assert len(prompts.version()) == 8
    assert prompts.section("Раздел", FACTS).version == prompts.version()


def test_validate_renders_section_prompt():
    builder_prompts.validate()
