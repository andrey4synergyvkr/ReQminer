from __future__ import annotations

import pytest

from contracts.stores import ChunkStore, KnowledgeStore, RunStore
from services.common import db, graph_db
from services.extractor.repository import InMemoryKnowledgeRepository
from services.ingestor.repository import InMemoryChunkRepository
from services.orchestrator import registry as registry_module

TEST_DB = "reqminer_test"
TEST_URL = f"postgresql+psycopg://reqminer:reqminer@localhost:5432/{TEST_DB}"
GRAPH_PREFIX = "2026-8"

_pg_available: bool | None = None
_neo4j_available: bool | None = None


def _create_test_database() -> bool:
    global _pg_available
    if _pg_available is not None:
        return _pg_available
    try:
        from sqlalchemy import create_engine, text

        base_url = TEST_URL.rsplit("/", 1)[0] + "/reqminer"
        engine = create_engine(
            base_url, pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
        engine.dispose()
        _pg_available = True
    except Exception:  # noqa: BLE001
        _pg_available = False
    return _pg_available


def _pg_clean() -> None:
    from sqlalchemy import text
    from sqlmodel import Session

    engine = db.get_engine()
    if engine is None:
        return
    with Session(engine) as session:
        for table in ("document_chunks", "source_artifacts",
                      "registry_packages", "registry_runs"):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


def _graph_clean(driver) -> None:
    if driver is None:
        return
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n.package STARTS WITH $prefix OR "
            "n.uid STARTS WITH $prefix DETACH DELETE n",
            prefix=GRAPH_PREFIX,
        )


@pytest.fixture
def pg_env(monkeypatch):
    if not _create_test_database():
        pytest.skip("PostgreSQL недоступен: docker compose up -d db")
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    db.reset_engine()
    import services.ingestor.repository_pg  # noqa: F401
    import services.orchestrator.registry_pg  # noqa: F401

    if not db.init_db():
        pytest.skip("PostgreSQL недоступен: схема не создана")
    _pg_clean()
    yield
    _pg_clean()
    db.reset_engine()


@pytest.fixture
def neo4j_env(monkeypatch):
    global _neo4j_available
    if _neo4j_available is False:
        pytest.skip("Neo4j недоступен: docker compose up -d graph")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "reqminer")
    graph_db.reset_driver()
    driver = graph_db.get_driver()
    if driver is None:
        _neo4j_available = False
        pytest.skip("Neo4j недоступен: docker compose up -d graph")
    _neo4j_available = True
    graph_db.init_graph()
    _graph_clean(driver)
    yield
    _graph_clean(driver)
    graph_db.reset_driver()


@pytest.fixture(params=["memory", "pg"])
def chunk_store(request):
    if request.param == "memory":
        store = InMemoryChunkRepository()
    else:
        request.getfixturevalue("pg_env")
        from services.ingestor.repository_pg import SqlChunkRepository

        store = SqlChunkRepository()
    assert isinstance(store, ChunkStore)
    yield store
    store.reset()


@pytest.fixture(params=["memory", "neo4j"])
def knowledge_store(request):
    if request.param == "memory":
        store = InMemoryKnowledgeRepository()
    else:
        request.getfixturevalue("neo4j_env")
        from services.extractor.repository_neo4j import Neo4jKnowledgeRepository

        store = Neo4jKnowledgeRepository()
    assert isinstance(store, KnowledgeStore)
    yield store
    if request.param == "memory":
        store.reset()


@pytest.fixture(params=["memory", "pg"])
def run_store(request, tmp_path):
    inbox = tmp_path / "inbox"
    if request.param == "memory":
        store = registry_module.InMemoryRegistry()
        store.inbox_root = inbox
        store._configured = True
    else:
        request.getfixturevalue("pg_env")
        from services.orchestrator.registry_pg import SqlRegistry

        store = SqlRegistry(inbox)
    assert isinstance(store, RunStore)
    yield store
    store.reset()
