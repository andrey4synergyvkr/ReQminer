from __future__ import annotations

from services.common import settings
from services.common.logging import get_logger

log = get_logger("common.graph_db")

_driver = None
_driver_checked = False  # попытка подключения уже была (липкий отказ)


def graph_uri() -> str | None:
    """Адрес Neo4j из окружения или .env; None, если не задан."""
    return settings.neo4j_uri()


def get_driver():
    """Ленивый driver-синглтон (neo4j); None без NEO4J_URI.

    Первый вызов подсоединяется к СУБД: ошибка подключения логируется
    как WARNING, приложение продолжает работу на in-memory хранилище.
    """
    global _driver, _driver_checked
    if _driver is not None:
        return _driver
    if _driver_checked:
        # отказ запоминается: каждый вызов фасада не платит connect-таймаут
        return None
    _driver_checked = True
    uri = graph_uri()
    if not uri:
        return None
    from neo4j import GraphDatabase

    try:
        # connection_timeout: остановленный контейнер (порт держит
        # Docker-прокси и не отвечает) дает быстрый отказ
        _driver = GraphDatabase.driver(
            uri,
            auth=(settings.neo4j_user(), settings.neo4j_password()),
            connection_timeout=3,
        )
        _driver.verify_connectivity()
        log.info("Neo4j подключен: %s", uri)
    except Exception as exc:  # noqa: BLE001 - работоспособность без БД важнее
        log.warning("Neo4j недоступен (%s), хранилище Knowledge in-memory", exc)
        _driver = None
    return _driver


def init_graph() -> bool:
    """Создает ограничения схемы и возвращает успех подключения.

    Уникальность Fact.uid и Source.uid - основа идемпотентности записи
    (MERGE по uid). Вызывается бэкендом Knowledge при первом обращении.
    """
    driver = get_driver()
    if driver is None:
        return False
    constraints = (
        "CREATE CONSTRAINT fact_uid IF NOT EXISTS "
        "FOR (f:Fact) REQUIRE f.uid IS UNIQUE",
        "CREATE CONSTRAINT source_uid IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.uid IS UNIQUE",
    )
    with driver.session() as session:
        for query in constraints:
            session.run(query)
    return True


def reset_driver() -> None:
    """Сброс синглтона (тесты: смена NEO4J_URI на лету)."""
    global _driver, _driver_checked
    if _driver is not None:
        _driver.close()
    _driver = None
    _driver_checked = False
