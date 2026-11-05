from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Field, Session, SQLModel, select

from services.common.logging import get_logger

log = get_logger("common.llm_cache_pg")

_table_ready = False
_table_lock = threading.Lock()


class LlmCacheRow(SQLModel, table=True):
    """Ответ модели по хэшу промпта; ключ - первичный ключ (идемпотентность)."""

    __tablename__ = "llm_cache"

    key: str = Field(primary_key=True)
    model: Optional[str] = None
    response: str
    created_at: str = ""


def _engine():
    """Engine PostgreSQL или None, если СУБД не настроена/недоступна."""
    from services.common import db

    return db.get_engine()


def _session() -> Session | None:
    global _table_ready
    engine = _engine()
    if engine is None:
        return None
    if not _table_ready:
        # таблица кэша создается при первом обращении: llm_cache не требует,
        # чтобы его модель импортировалась до db.init_db (ср. registry_pg)
        with _table_lock:
            if not _table_ready:
                SQLModel.metadata.create_all(engine)
                _table_ready = True
    return Session(engine)


def get(key: str) -> str | None:
    """Ответ модели из таблицы; None без СУБД и при отсутствии записи."""
    session = _session()
    if session is None:
        return None
    with session:
        row = session.exec(select(LlmCacheRow).where(LlmCacheRow.key == key)).first()
    return row.response if row else None


def put(key: str, response: str, model: str | None = None) -> None:
    """Сохраняет ответ; параллельные записи одного ключа не конфликтуют.

    Вместо read-modify-write используется UPSERT ON CONFLICT: два потока
    пула на одинаковом промпте не получают IntegrityError.
    """
    session = _session()
    if session is None:
        return
    created = datetime.now().isoformat(timespec="seconds")
    with session:
        statement = (
            pg_insert(LlmCacheRow)
            .values(key=key, model=model, response=response, created_at=created)
            .on_conflict_do_update(
                index_elements=[LlmCacheRow.key],
                set_={"model": model, "response": response,
                      "created_at": created},
            )
        )
        session.execute(statement)
        session.commit()


def clear() -> None:
    """Очистка таблицы кэша."""
    from sqlmodel import delete

    session = _session()
    if session is None:
        return
    with session:
        session.exec(delete(LlmCacheRow))
        session.commit()


def reset_backend() -> None:
    """Сброс признака готовности таблицы (тесты: смена DATABASE_URL)."""
    global _table_ready
    with _table_lock:
        _table_ready = False
