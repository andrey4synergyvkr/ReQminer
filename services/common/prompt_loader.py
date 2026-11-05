from __future__ import annotations

from services.common import templating

_PROMPTS = templating.TemplateSet("services.common", "prompts")


def render(name: str, **context) -> str:
    """Рендерит промпт по имени; *.md - статический, *.md.j2 - шаблон Jinja2."""
    return _PROMPTS.render(name, **context).strip()


def version() -> str:
    """Версия набора промптов - короткий SHA-256 их содержимого.

    Пишется в стартовый лог: прогон можно сопоставить с формулировками,
    на которых он выполнялся (воспроизводимость контрольного примера).
    Версия считается по содержимому, а не по mtime: package resources
    в wheel не имеют предсказуемых времён изменения.
    """
    return _PROMPTS.version()


def names() -> list[str]:
    """Файлы набора промптов (относительные пути)."""
    return _PROMPTS.names()


def reset() -> None:
    """Сброс кэшей (тесты: правка шаблонов на лету)."""
    templating.reset()
