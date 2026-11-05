from __future__ import annotations

from services.common import templating
from services.common.prompts import Prompt

_PROMPTS = templating.TemplateSet("services.builder", "templates/prompts")


class BuilderPromptSet:
    """Набор промптов генерации разделов документов."""

    def section(self, title: str, facts: list[dict]) -> Prompt:
        """Готовит промпт раздела из заголовка и фактов."""
        return Prompt(
            name="section",
            system=_PROMPTS.render("section_system.md").strip(),
            user=_PROMPTS.render(
                "section_user.md.j2", title=title, facts=facts
            ).strip(),
            version=_PROMPTS.version(),
        )

    def version(self) -> str:
        """Версия набора промптов Builder."""
        return _PROMPTS.version()

    def validate(self) -> None:
        """Рендерит промпт с фиктивным контекстом на старте приложения."""
        try:
            self.section("Проверка", [])
        except Exception as exc:  # noqa: BLE001 - сообщение важнее типа
            raise RuntimeError(
                "Набор промптов Builder не прошёл проверку шаблонов"
            ) from exc


builder_prompts = BuilderPromptSet()
