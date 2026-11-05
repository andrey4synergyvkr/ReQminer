from __future__ import annotations

import os
from pathlib import Path

from services.common import dotenv

_loaded = False


def load() -> None:
    """Подгружает .env один раз; переменные окружения важнее файла."""
    global _loaded
    if not _loaded:
        dotenv.load()
        _loaded = True


def _get(name: str, default: str = "") -> str:
    load()
    return os.environ.get(name, default).strip()


def database_url() -> str | None:
    """DATABASE_URL или None (пустая строка = не задана)."""
    return _get("DATABASE_URL") or None


def neo4j_uri() -> str | None:
    """NEO4J_URI или None (пустая строка = не задан)."""
    return _get("NEO4J_URI") or None


def neo4j_user() -> str:
    """Пользователь Neo4j."""
    return _get("NEO4J_USER", "neo4j")


def neo4j_password() -> str:
    """Пароль Neo4j."""
    return _get("NEO4J_PASSWORD", "reqminer")


def llm_api_key() -> str:
    """Ключ провайдера LLM; пустая строка включает offline-режим."""
    return _get("LLM_API_KEY")


def llm_model() -> str:
    """Имя модели LLM."""
    return _get("LLM_MODEL", "~z-ai/glm-latest")


def llm_base_url() -> str:
    """Адрес Anthropic-совместимого шлюза."""
    return _get("LLM_BASE_URL", "https://routerai.ru/api")


def llm_concurrency() -> int:
    """Число потоков LLM; 0 - последовательный режим, битое значение - 4."""
    try:
        return max(int(_get("LLM_CONCURRENCY", "4")), 0)
    except ValueError:
        return 4


def llm_cache_enabled() -> bool:
    """Включён ли кэш ответов модели."""
    return _get("LLM_CACHE", "1").lower() not in ("0", "off", "false")


def log_level() -> str:
    """Уровень журналирования."""
    return _get("LOG_LEVEL", "INFO").upper()


def outbox_root() -> Path:
    """Корневой каталог каркасов документов."""
    return Path(_get("OUTBOX_ROOT", "outbox"))


def validate() -> None:
    """Проверяет, что для заданных СУБД установлены их extras.

    Ошибка конфигурации видна на старте с понятным сообщением, а не
    ImportError в глубине первого запроса.
    """
    if database_url():
        try:
            import sqlalchemy  # noqa: F401 - проверка extra [db]
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL задан, но extra [db] не установлен "
                "(pip install -e \".[db]\")"
            ) from exc
    if neo4j_uri():
        try:
            import neo4j  # noqa: F401 - проверка extra [graph]
        except ImportError as exc:
            raise RuntimeError(
                "NEO4J_URI задан, но extra [graph] не установлен "
                "(pip install -e \".[graph]\")"
            ) from exc
