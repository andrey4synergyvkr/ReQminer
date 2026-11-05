from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.builder import writer as outbox_writer  # noqa: E402
from services.common import db, graph_db  # noqa: E402
from services.common.logging import LOG_DIR, get_logger  # noqa: E402

log = get_logger("scripts.db_clean")

PG_TABLES = (
    "registry_packages",
    "registry_runs",
    "document_chunks",
    "source_artifacts",
    "llm_cache",
)


def clean_postgres() -> bool | None:
    """TRUNCATE таблиц."""
    if db.database_url() is None:
        return None
    if db.get_engine() is None:
        print("PostgreSQL не подключен: поднимите контейнер (make db-up)")
        return False
    from sqlalchemy import inspect, text
    from sqlmodel import Session

    with Session(db.get_engine()) as session:
        # Таблица кэша LLM создается при первом облачном вызове - ее может
        # не быть в свежей БД, поэтому чистим только существующие таблицы.
        existing = set(inspect(session.connection()).get_table_names())
        names = [t for t in PG_TABLES if t in existing]
        if not names:
            print("PostgreSQL: таблиц для очистки нет")
            return True
        session.execute(text(
            f"TRUNCATE {', '.join(f'\"{t}\"' for t in names)} RESTART IDENTITY"
        ))
        session.commit()
    print(f"PostgreSQL очищен: {', '.join(names)}")
    return True


def clean_neo4j() -> bool | None:
    """DETACH DELETE узлов графа."""
    if graph_db.graph_uri() is None:
        return None
    driver = graph_db.get_driver()
    if driver is None:
        print("Neo4j не подключен: поднимите контейнер (make db-up)")
        return False
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
    print("Neo4j очищен: все узлы и связи")
    return True


def clean_outbox() -> bool | None:
    """Удаление каркасов из outbox."""
    root = outbox_writer._root()
    if not root.is_dir():
        return None
    shutil.rmtree(root)
    print(f"Outbox очищен: {root}")
    return True


def clean_logs() -> bool | None:
    """
    Удаление журналов logs/*.log*
    """
    if not LOG_DIR.is_dir():
        return None
    removed = []
    for path in sorted(LOG_DIR.glob("*.log*")):
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            print(f"Журнал {path.name} не удален: занят работающим приложением (make stop)")
            return True
    print(f"Логи очищены: {', '.join(removed)}" if removed else "Логи: удалять нечего")
    return True


def main() -> int:
    """Очищает PostgreSQL, Neo4j, outbox и логи."""
    results = [clean_postgres(), clean_neo4j(), clean_outbox(), clean_logs()]
    if all(r is None for r in results):
        print("Хранилища не настроены: задайте DATABASE_URL/NEO4J_URI (см. .env.example)")
        return 1
    print("Приложение стартует пустым; контрольный пример — make seed")
    return 0 if all(r is not False for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
