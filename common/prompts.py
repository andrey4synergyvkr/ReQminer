from __future__ import annotations

import json
import re
from dataclasses import dataclass

from contracts.workflow import PairKind
from services.common import prompt_loader

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


@dataclass(frozen=True)
class Prompt:
    """Готовое сообщение модели: system + user и версия набора."""

    name: str
    system: str
    user: str
    version: str


class PromptSet:
    """Набор промптов Extractor-а с явными методами."""

    def extract(self, fragment: str) -> Prompt:
        """Готовит промпт извлечения кандидатов из фрагмента."""
        return self._build(
            "extract", "extract_system.md", "extract_user.md.j2",
            fragment=fragment,
        )

    def judge_pair(self, a: dict, b: dict) -> Prompt:
        """Готовит промпт сравнения двух фактов."""
        return self._build(
            "judge_pair", "judge_pair_system.md", "judge_pair_user.md.j2",
            a=a.get("title"), b=b.get("title"),
        )

    def version(self) -> str:
        """Версия набора промптов - короткий хэш содержимого."""
        return prompt_loader.version()

    def validate(self) -> None:
        """Рендерит все промпты с фиктивным контекстом.

        Ловит отсутствующий файл или забытую переменную на старте,
        а не в первом вызове модели.
        """
        try:
            self.extract("Проверка")
            self.judge_pair({"title": "А"}, {"title": "Б"})
        except Exception as exc:  # noqa: BLE001 - сообщение важнее типа
            raise RuntimeError(
                "Набор промптов не прошёл проверку шаблонов"
            ) from exc

    @staticmethod
    def parse_candidates(text: str) -> list[dict]:
        """Кандидаты из ответа модели; невалидный JSON - пустой список."""
        data = PromptSet._json(text)
        if not isinstance(data, dict):
            return []
        candidates = data.get("candidates", [])
        if not isinstance(candidates, list):
            return []
        return [
            cand for cand in candidates
            if isinstance(cand, dict) and cand.get("title")
        ]

    @staticmethod
    def parse_verdict(text: str) -> dict | None:
        """Вердикт о паре; неизвестный kind или битый JSON - None."""
        data = PromptSet._json(text)
        if not isinstance(data, dict):
            return None
        if data.get("kind") not in (
            PairKind.DUPLICATE.value, PairKind.CONTRADICTION.value
        ):
            return None
        return {"kind": data["kind"], "reason": data.get("reason", "")}

    @staticmethod
    def _json(text: str) -> object | None:
        try:
            return json.loads(_FENCE.sub("", text.strip()))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _build(name: str, system_file: str, user_file: str,
               **context) -> Prompt:
        return Prompt(
            name=name,
            system=prompt_loader.render(system_file),
            user=prompt_loader.render(user_file, **context),
            version=prompt_loader.version(),
        )


prompts = PromptSet()
