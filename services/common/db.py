from __future__ import annotations

from services.common import settings
from services.common.logging import get_logger

log = get_logger("common.db")

_engine = None
_engine_checked = False  # попытка подключения уже была (липкий отказ)


def database_url() -> str | None:
    """Адрес PostgreSQL из окружения или .env; None, если не задан."""
    return settings.database_url()


def get_engine():
    """Ленивый engine-синглтон (SQLAlchemy); None без DATABASE_URL.

    Первый вызов подсоединяется к СУБД: ошибка подключения логируется
    как WARNING, приложение продолжает работу на in-memory хранилищах.
    """
    global _engine, _engine_checked
    if _engine is not None:
        return _engine
    if _engine_checked:
        # отказ запоминается: иначе каждый вызов фасада платит connect-таймаут
        return None
    _engine_checked = True
    url = database_url()
    if not url:
        return None
    from sqlalchemy import create_engine

    try:
        # connect_timeout: при остановленной СУБД (порт закрыт прокси
        # Docker) отказ фиксируется за секунды, а не за минуты
        _engine = create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        # проверка соединения сразу, а не при первом запросе:
        # недоступная БД переводит хранилища в in-memory режим явно
        from sqlalchemy import text

        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("PostgreSQL подключен: %s", _mask(url))
    except Exception as exc:  # noqa: BLE001 - работоспособность без БД важнее
        log.warning("PostgreSQL недоступен (%s), хранилища in-memory", exc)
        _engine = None
    return _engine


def init_db() -> bool:
    """Создает схему (create_all) и возвращает успех подключения.

    SQLModel-модули с таблицами должны быть импортированы вызывающим
    кодом ДО этого вызова: их модели попадают в общую metadata.
    """
    engine = get_engine()
    if engine is None:
        return False
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(engine)
    _ensure_progress_column(engine)
    return True


def _ensure_progress_column(engine) -> None:
    """Аддитивная миграция существующей БД: колонка прогресса прогона.

    create_all не добавляет колонки в уже созданные таблицы, поэтому
    колонка добавляется отдельным ALTER ... IF NOT EXISTS. Повторный
    вызов безопасен, пересоздавать БД не нужно.
    """
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE IF EXISTS registry_runs "
            "ADD COLUMN IF NOT EXISTS progress TEXT NOT NULL DEFAULT '{}'"
        ))


def reset_engine() -> None:
    """Сброс синглтона (тесты: смена DATABASE_URL на лету)."""
    global _engine, _engine_checked
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_checked = False


def _mask(url: str) -> str:
    """URL без пароля - для логов."""
    if "://" in url and "@" in url:
        scheme, _, rest = url.partition("://")
        creds, _, host = rest.rpartition("@")
        user = creds.partition(":")[0]
        return f"{scheme}://{user}:***@{host}"
    return url
