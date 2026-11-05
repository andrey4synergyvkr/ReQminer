from __future__ import annotations

import hashlib
import threading

from services.common import settings
from services.common.logging import get_logger

log = get_logger("common.llm_cache")

# Ответы моделей крупные: без лимита словарь рос бы вместе с корпусом.
MAX_ENTRIES = 500

_memory: dict[str, str] = {}
_hits = 0
_misses = 0
# кэш пишется из пула потоков (parallel.map_calls): вытеснение и счетчики
_lock = threading.Lock()


def enabled() -> bool:
    """Кэш включен, если LLM_CACHE не задан или не равен 0/off/false."""
    return settings.llm_cache_enabled()


def key(model: str, system: str, user: str) -> str:
    """Ключ кэша: модель и оба промпта (разделитель - NUL, не встречается в тексте)."""
    digest = hashlib.sha256()
    for part in (model, system, user):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def get(cache_key: str) -> str | None:
    """Ответ модели из кэша; L1, затем L2 (найденное поднимается в L1)."""
    text = _memory.get(cache_key)
    if text is None:
        text = _from_pg(cache_key)
        if text is not None:
            _remember(cache_key, text)
    _count(hit=text is not None)
    return text


def set(cache_key: str, text: str, model: str = "") -> None:  # noqa: A001
    """Запоминает ответ модели в L1 и, если доступна СУБД, в L2."""
    _remember(cache_key, text)
    _to_pg(cache_key, text, model)


def stats() -> dict:
    """Счётчики попаданий и промахов (диагностика и логи прогона)."""
    return {"hits": _hits, "misses": _misses, "entries": len(_memory)}


def reset() -> None:
    """Очистка кэша (тесты; L2 не трогается, чтобы не платить за БД)."""
    global _hits, _misses
    _memory.clear()
    _hits = _misses = 0


def _remember(cache_key: str, text: str) -> None:
    _memory[cache_key] = text
    with _lock:
        while len(_memory) > MAX_ENTRIES:
            # FIFO по порядку вставки: дольше всего неиспользуемые уходят первыми
            _memory.pop(next(iter(_memory)), None)


def _count(hit: bool) -> None:
    global _hits, _misses
    with _lock:
        if hit:
            _hits += 1
        else:
            _misses += 1


# --- L2: PostgreSQL (опционально, ленивый импорт зависимостей db) ------------

def _from_pg(cache_key: str) -> str | None:
    try:
        from services.common import llm_cache_pg

        return llm_cache_pg.get(cache_key)
    except Exception as exc:  # noqa: BLE001 - кэш не должен ломать прогон
        log.warning("L2-кэш LLM недоступен: %s", exc)
        return None


def _to_pg(cache_key: str, text: str, model: str = "") -> None:
    try:
        from services.common import llm_cache_pg

        llm_cache_pg.put(cache_key, text, model)
    except Exception as exc:  # noqa: BLE001 - кэш не должен ломать прогон
        log.warning("L2-кэш LLM недоступен: %s", exc)
