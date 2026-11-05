from __future__ import annotations

import threading
import time

from services.common import llm_cache, parallel, settings
from services.common.logging import get_logger
from services.common.prompts import prompts
from services.common.text_rules import offline_candidates, offline_verdict

log = get_logger("common.llm_adapter")

_RETRIES = 3
_RETRY_PAUSE = 1.0
_MAX_TOKENS = 4096


class _BaseAdapter:
    """Общая часть: журналы вызовов и счётчик повторов.

    Методы адаптера вызываются и из пула потоков parallel.map_calls,
    поэтому журналы и счётчик повторов защищены блокировкой.
    """

    # имя модели - часть ключа кэша; облачный адаптер задает его в __init__
    _model = ""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.verdicts: list[dict] = []   # вердикты о парах (Extractor)
        self.retries = 0                 # повторные вызовы модели (llm_retries)
        self._lock = threading.Lock()

    def _record(self, journal: list[dict], entry: dict) -> None:
        """Запись в журнал вызовов (безопасна при конкурентных вызовах)."""
        with self._lock:
            journal.append(entry)

    def _count_retry(self) -> None:
        """Инкремент метрики llm_retries без потери обновлений в потоках."""
        with self._lock:
            self.retries += 1

    def complete(self, system: str, user: str) -> str | None:
        """Возвращает ответ модели на готовый промпт."""
        raise NotImplementedError

    def extract_candidates(self, fragment_text: str) -> list[dict]:
        """Извлекает кандидатов требований из фрагмента."""
        raise NotImplementedError

    def judge_pair(self, a: dict, b: dict) -> dict | None:
        """Возвращает вердикт о паре фактов."""
        raise NotImplementedError


class OfflineLlmAdapter(_BaseAdapter):
    """Без ключа: модель не вызывается, тексты документов - из шаблонов."""

    def __init__(self) -> None:
        super().__init__(mode="offline")

    def complete(self, system: str, user: str) -> str | None:
        """Offline-режим не ходит в модель: Builder рендерит шаблон."""
        return None

    def extract_candidates(self, fragment_text: str) -> list[dict]:
        """Извлекает кандидатов детерминированными правилами."""
        return offline_candidates(fragment_text)

    def judge_pair(self, a: dict, b: dict) -> dict | None:
        """Сравнивает пару детерминированными правилами."""
        verdict = offline_verdict(a, b)
        self._record(self.verdicts, {"a": a.get("id"), "b": b.get("id"), "verdict": verdict})
        return verdict


class CloudLlmAdapter(_BaseAdapter):
    """Облачный LLM через Anthropic-совместимый шлюз; fallback - offline."""

    def __init__(self) -> None:
        super().__init__(mode="cloud")
        # импорт только в облачном режиме: тесты и демо работают без SDK
        import anthropic  # noqa: PLC0415

        self._model = settings.llm_model()
        self._client = anthropic.Anthropic(
            api_key=settings.llm_api_key(),
            base_url=settings.llm_base_url(),
        )
        log.info(
            "Промпты LLM: версия %s (services/common/prompts); кэш ответов %s; "
            "вызовов в полёте %d",
            prompts.version(),
            "включен" if llm_cache.enabled() else "отключен (LLM_CACHE=0)",
            parallel.worker_count(self),
        )

    def _ask(self, system: str, user: str) -> str:
        """Один вызов модели; повторы и счетчик - на стороне вызывающего."""
        response = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        log.debug("Вызов модели %s: промпт %d симв., ответ %d симв.",
                  self._model, len(system) + len(user), len(text))
        return text

    def _ask_with_retries(self, system: str, user: str) -> str | None:
        """Вызов модели с повторами; повторный промпт берется из кэша (llm_cache)."""
        cache_key = None
        if llm_cache.enabled():
            cache_key = llm_cache.key(self._model, system, user)
            cached = llm_cache.get(cache_key)
            if cached is not None:
                log.debug("Ответ модели из кэша: %s", cache_key[:12])
                return cached
        for attempt in range(1, _RETRIES + 1):
            try:
                text = self._ask(system, user)
                if text:
                    if cache_key is not None:
                        llm_cache.set(cache_key, text, self._model)
                    return text
                raise ValueError("пустой ответ модели")
            except Exception as exc:  # noqa: BLE001 - после всех попыток fallback
                if attempt == _RETRIES:
                    log.warning(
                        "Вызов модели не удался после %d попыток "
                        "(последняя ошибка: %s) — откат на детерминированные правила",
                        _RETRIES, exc,
                    )
                    return None
                self._count_retry()
                log.debug(
                    "Вызов модели не удался (попытка %d/%d): %s — повтор через %s c",
                    attempt, _RETRIES, exc, _RETRY_PAUSE,
                )
                time.sleep(_RETRY_PAUSE)
        return None

    # --- Builder: текст раздела --------------------------------------------

    def complete(self, system: str, user: str) -> str | None:
        """Ответ модели на готовый промпт; None - недоступна/пустой ответ."""
        return self._ask_with_retries(system, user)

    # --- Extractor: извлечение кандидатов и вердикты о парах ----------------

    def extract_candidates(self, fragment_text: str) -> list[dict]:
        """Извлекает кандидатов через модель; при сбое - offline-правила."""
        prompt = prompts.extract(fragment_text)
        text = self._ask_with_retries(prompt.system, prompt.user)
        if text:
            candidates = prompts.parse_candidates(text)
            if candidates:
                return candidates
            log.debug("Ответ модели без распознаваемых кандидатов — offline-правила")
            self._count_retry()
        return offline_candidates(fragment_text)

    def judge_pair(self, a: dict, b: dict) -> dict | None:
        """Сравнивает пару через модель; при сбое - offline-правила."""
        prompt = prompts.judge_pair(a, b)
        text = self._ask_with_retries(prompt.system, prompt.user)
        verdict = prompts.parse_verdict(text) if text else None
        if verdict is None:
            verdict = offline_verdict(a, b)
        self._record(self.verdicts, {"a": a.get("id"), "b": b.get("id"), "verdict": verdict})
        return verdict


_adapter: _BaseAdapter | None = None


def get_adapter() -> _BaseAdapter:
    """Возвращает общий адаптер, выбирая режим по наличию LLM_API_KEY.

    В облачном режиме вызовы идут через Anthropic-совместимый шлюз с
    повторами и кэшем ответов; без ключа работает offline: тексты разделов
    рендерятся шаблонами, а кандидаты извлекаются детерминированными правилами.
    """
    global _adapter
    if _adapter is None:
        _adapter = (
            CloudLlmAdapter() if settings.llm_api_key()
            else OfflineLlmAdapter()
        )
        log.info(
            "LLM-адаптер: %s режим%s",
            _adapter.mode,
            f" (модель {settings.llm_model()})"
            if _adapter.mode == "cloud" else " (LLM_API_KEY не задан)",
        )
    return _adapter


def reset_adapter() -> None:
    """Сброс синглтона (тесты и смена настроек без перезапуска)."""
    global _adapter
    _adapter = None
