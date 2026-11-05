from __future__ import annotations

import json

import pytest
from pytest_bdd import given, parsers, then, when

TEST_DB = "reqminer_test"
TEST_URL = f"postgresql+psycopg://reqminer:reqminer@localhost:5432/{TEST_DB}"

GRAPH_TEST_PREFIX = "2026-9"


def _pg_available() -> bool:
    from services.common import db

    db.reset_engine()
    import os

    os.environ["DATABASE_URL"] = TEST_URL
    db.reset_engine()
    if db.get_engine() is None:
        return False
    return True


@pytest.fixture
def pg_state() -> dict:
    return {}


def _create_test_database() -> bool:
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
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=True)
def clean_pg_state():
    yield
    import os

    from services.common import db

    if db.get_engine() is not None and "reqminer_test" in str(
        db.get_engine().url
    ):
        from sqlalchemy import text
        from sqlmodel import Session

        with Session(db.get_engine()) as session:
            for table in ("document_chunks", "source_artifacts",
                          "registry_packages", "registry_runs"):
                session.execute(text(f"DELETE FROM {table}"))
            session.commit()
    db.reset_engine()
    os.environ.pop("DATABASE_URL", None)
    from services.ingestor import repository as repo_mod
    from services.orchestrator import registry as reg_mod

    repo_mod.chunks_repo.reset_backend()
    reg_mod.reset_backend()


@pytest.fixture(autouse=True)
def clean_graph_state():
    yield
    import os

    from services.common import graph_db

    driver = graph_db.get_driver()
    if driver is not None:
        with driver.session() as session:
            session.run(
                "MATCH (n) WHERE n.package STARTS WITH $prefix OR "
                "n.uid STARTS WITH $prefix2 DETACH DELETE n",
                prefix=GRAPH_TEST_PREFIX, prefix2=GRAPH_TEST_PREFIX,
            )
    graph_db.reset_driver()
    os.environ.pop("NEO4J_URI", None)
    from services.extractor import repository as knowledge_mod

    knowledge_mod.knowledge_repo.reset_backend()


@given('хранилище Chunks работает на PostgreSQL')
@given('реестр работает на PostgreSQL')
def storage_on_postgres(request):
    if not _create_test_database():
        pytest.skip("PostgreSQL недоступен: docker compose up -d db")
    import os

    from services.common import db

    os.environ["DATABASE_URL"] = TEST_URL
    db.reset_engine()
    request.node.add_marker(pytest.mark.db)


@given(parsers.parse('пакет "{pid}" прогнан через Ingestor'))
def package_ingested(pg_state, pid):
    from pathlib import Path

    from services.ingestor import scanner
    from services.orchestrator import registry

    inbox = pg_state.get("inbox_root")
    if inbox is None:
        inbox = pg_state.setdefault("inbox_root", Path("services/web_ui/data/uploads"))
    scanner.process_package(pid, registry.inbox_dir(pid))


@given(parsers.parse('прогон пакета "{pid}" завершен с состоянием "{state}"'))
def run_finished_with_state(pg_state, pid, state):
    from services.orchestrator import registry

    registry.set_run(pid, {
        "state": state,
        "started": "2026-10-23T10:00:00",
        "stages": [
            {"service": "Ingestor", "mod": "нарезка и парсинг документов",
             "status": "done", "processed": "1 документа, 2 фрагментов"},
        ],
        "metrics": {"fragments": 2, "facts": 2, "llm_retries": 0, "quarantine": 0},
        "finished": "23.10.2026 10:00",
    })


@given(parsers.parse('пакет "{pid}" зарегистрирован с документом "{doc}" в inbox'))
def register_package_doc(pg_state, pid, doc, tmp_path):
    from services.orchestrator import registry

    inbox_root = tmp_path / "uploads"
    pg_state["inbox_root"] = inbox_root
    registry.reset_backend()
    registry.configure(inbox_root, force=True)
    registry.create_package(
        f"Пакет {pid}", "обращение заказчика",
        [{"name": doc, "type": "не определен",
          "content": "# Требования\n\n"
                     "Как аналитик, я хочу загружать входящие документы.\n\n"
                     "# Ограничения\n\n"
                     "Время отклика интерфейса не должно превышать двух секунд.\n"
                     .encode("utf-8")}],
        pid=pid,
    )
    pg_state["package"] = pid


@when('приложение перезапускается')
def restart_app(pg_state):
    from pathlib import Path

    from services.common import db, graph_db

    db.reset_engine()
    graph_db.reset_driver()
    from services.extractor import repository as knowledge_mod
    from services.ingestor import repository as repo_mod
    from services.orchestrator import registry as reg_mod

    repo_mod.chunks_repo.reset_backend()
    knowledge_mod.knowledge_repo.reset_backend()
    reg_mod.reset_backend()
    inbox = pg_state.get("inbox_root", Path("services/web_ui/data/uploads"))
    reg_mod.configure(inbox, force=True)


@when(parsers.parse('пакет "{pid}" прогнан через Ingestor повторно'))
def package_reingested(pg_state, pid):
    package_ingested(pg_state, pid)


@when('сид контрольного примера загружается дважды')
def seed_twice():
    from services.ingestor.repository import chunks_repo

    chunks_repo.seed_demo("2026-042")
    chunks_repo.seed_demo("2026-042")


@when('аналитик создает новый пакет через форму')
def create_new_package(pg_state, tmp_path):
    from services.orchestrator import registry

    inbox = pg_state.get("inbox_root", tmp_path / "uploads")
    pkg = registry.create_package(
        "новый пакет", "обращение заказчика",
        [{"name": "doc.md", "type": "не определен",
          "content": "текст документа".encode("utf-8")}],
    )
    pg_state["new_package"] = pkg["id"]


@when(parsers.parse('аналитик загружает пакет "{pid}" с документами "{doc1}" и "{doc2}"'))
def upload_mixed_package(pg_state, tmp_path, pid, doc1, doc2):
    from services.orchestrator import registry

    inbox = tmp_path / "uploads"
    pg_state["inbox_root"] = inbox
    pg_state["uploaded"] = [doc1, doc2]
    registry.reset_backend()
    registry.configure(inbox, force=True)
    registry.create_package(
        f"Пакет {pid}", "обращение заказчика",
        [
            {"name": doc1, "type": "не определен",
             "content": "# Требования\n".encode("utf-8")},
            {"name": doc2, "type": "не определен",
             "content": b"%PDF-1.4 demo"},
        ],
        pid=pid,
    )
    pg_state["package"] = pid


@then(parsers.parse('фрагменты пакета "{pid}" доступны из PostgreSQL'))
def fragments_available(pg_state, pid):
    from services.ingestor.repository import chunks_repo

    chunks = chunks_repo.list_chunks(pid)
    assert chunks, "фрагменты не пережили перезапуск"
    assert chunks_repo.backend_name() == "SqlChunkRepository"


@then(parsers.parse('статистика пакета "{pid}" показывает документов {documents:d} и фрагментов {fragments:d}'))
def stats_show(pg_state, pid, documents, fragments):
    from services.ingestor.repository import chunks_repo

    stats = chunks_repo.stats(pid)
    assert stats["documents"] == documents, stats
    assert stats["fragments"] == fragments, stats


@then(parsers.parse('артефакт документа "{doc}" пакета "{pid}" не дублируется'))
def artifact_not_duplicated(pg_state, doc, pid):
    from services.ingestor.repository import chunks_repo

    artifacts = [a for a in chunks_repo.list_artifacts(pid) if a.file_name == doc]
    assert len(artifacts) == 1, f"артефакт задублирован: {len(artifacts)}"


@then(parsers.parse('пакет "{pid}" есть в реестре'))
def package_in_registry(pg_state, pid):
    from services.orchestrator import registry

    assert registry.get_package(pid) is not None
    assert registry.backend_name() == "SqlRegistry"


@then(parsers.parse('запись прогона "{pid}" читается с состоянием "{state}"'))
def run_state_kept(pg_state, pid, state):
    from services.orchestrator import registry

    run = registry.get_run(pid)
    assert run is not None, "прогон не пережил перезапуск"
    assert run["state"] == state, run


@then(parsers.parse('этапы прогона "{pid}" сохранены'))
def run_stages_kept(pg_state, pid):
    from services.orchestrator import registry

    run = registry.get_run(pid)
    assert run["stages"], run
    assert run["stages"][0]["status"] == "done"


@then('номер нового пакета продолжает нумерацию реестра')
def package_numbering_continues(pg_state):
    from services.orchestrator import registry

    pid = pg_state["new_package"]
    number = int(pid.rsplit("-", 1)[1])
    max_seed = max(
        int(p["id"].rsplit("-", 1)[1]) for p in registry.list_packages()
        if p["id"] != pid
    )
    assert number == max_seed + 1, (pid, max_seed)


@then('реестр пакетов пуст')
def registry_is_empty():
    from services.orchestrator import registry

    assert registry.list_packages() == [], registry.list_packages()
    assert registry.backend_name() == "SqlRegistry"


@then(parsers.parse('форма пакета "{pid}" хранит оба файла без содержимого'))
def package_files_without_content(pg_state, pid):
    from services.orchestrator import registry

    pkg = registry.get_package(pid)
    assert pkg is not None
    files = {f["name"]: f for f in pkg["files"]}
    assert set(files) == set(pg_state["uploaded"]), files
    ok_doc, rejected_doc = pg_state["uploaded"]
    assert files[ok_doc]["verdict"] == "ok"
    assert files[rejected_doc]["verdict"] == "reject"
    assert all("content" not in f for f in pkg["files"]), pkg["files"]
    assert registry.backend_name() == "SqlRegistry"


@given('хранилище Knowledge работает на Neo4j')
def storage_on_neo4j(request):
    import os

    from services.common import graph_db

    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "reqminer")
    graph_db.reset_driver()
    if graph_db.get_driver() is None:
        pytest.skip("Neo4j недоступен: docker compose up -d graph")
    request.node.add_marker(pytest.mark.graph)


@given(parsers.parse('фрагменты пакета "{pid}" сидированы в Chunks'))
def fragments_seeded(pg_state, pid, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    from services.common.llm_adapter import reset_adapter

    reset_adapter()
    from contracts.ontology import DocumentChunk
    from services.ingestor.repository import chunks_repo

    chunks_repo.reset(pid)
    text = (
        "Как аналитик, я хочу загружать входящие документы.\n"
        "Время отклика интерфейса не должно превышать двух секунд.\n"
    )
    import hashlib

    chunks_repo.save(pid, _artifact(pid), [
        DocumentChunk(
            id=f"{pid}:doc.md:1", chunk_index=1, content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            start_offset=0, end_offset=len(text), token_count=len(text) // 4,
            metadata=json.dumps({"doc": "doc.md"}),
        ),
    ])
    pg_state["package"] = pid
    pg_state.setdefault("facts_before", None)
    pg_state.setdefault("pairs_before", None)


def _artifact(pid):
    from contracts.ontology import ParsingStatus, SourceArtifact

    return SourceArtifact(
        id=f"{pid}:doc.md", file_path="doc.md", file_name="doc.md",
        total_chunks=1, parsing_status=ParsingStatus.PARSED,
    )


@given(parsers.parse('пакет "{pid}" прогнан через Extractor'))
@when(parsers.parse('пакет "{pid}" прогнан через Extractor'))
def package_extracted(pg_state, pid):
    from services.extractor import service as extractor_service
    from services.extractor.repository import knowledge_repo

    knowledge_repo.reset(pid)
    extractor_service.extract(pid)
    if pg_state.get("facts_before") is None:
        pg_state["facts_before"] = knowledge_repo.facts_total(pid)
        pg_state["pairs_before"] = len(knowledge_repo.pairs_of(pid))


@when(parsers.parse('пакет "{pid}" прогнан через Extractor повторно'))
def package_reextracted(pg_state, pid):
    from services.extractor import service as extractor_service

    extractor_service.extract(pid)


@given(parsers.parse('аналитик подтверждает все факты пакета "{pid}"'))
def analyst_confirms_all(pg_state, pid):
    from contracts.ontology import LifecycleStatus
    from services.extractor.repository import knowledge_repo

    ids = [f["id"] for f in knowledge_repo.list_facts(pid)]
    knowledge_repo.review_facts(
        ids, LifecycleStatus.CONFIRMED.value, "Иванов И. И.", package=pid
    )


@then(parsers.parse('факты пакета "{pid}" доступны из Neo4j'))
def facts_available(pg_state, pid):
    from services.extractor.repository import knowledge_repo

    total = knowledge_repo.facts_total(pid)
    assert total > 0, "факты не пережили перезапуск"
    assert knowledge_repo.backend_name() == "Neo4jKnowledgeRepository"


@then(parsers.parse('пары-кандидаты пакета "{pid}" доступны из Neo4j'))
def pairs_available(pg_state, pid):
    from services.extractor.repository import knowledge_repo

    total = len(knowledge_repo.pairs_of(pid))
    assert total > 0, "пары не пережили перезапуск"
    assert knowledge_repo.backend_name() == "Neo4jKnowledgeRepository"


@then(parsers.parse('число фактов пакета "{pid}" не изменилось'))
def facts_unchanged(pg_state, pid):
    from services.extractor.repository import knowledge_repo

    now = knowledge_repo.facts_total(pid)
    assert now == pg_state["facts_before"], (now, pg_state["facts_before"])


@then(parsers.parse('число пар пакета "{pid}" не изменилось'))
def pairs_unchanged(pg_state, pid):
    from services.extractor.repository import knowledge_repo

    now = len(knowledge_repo.pairs_of(pid))
    assert now == pg_state["pairs_before"], (now, pg_state["pairs_before"])


@then(parsers.parse('граф пакета "{pid}" содержит узлы-факты и узлы-источники'))
def graph_has_nodes(pg_state, pid):
    from services.extractor.repository import knowledge_repo

    graph = knowledge_repo.get_graph(pid)
    assert graph["facts"], "нет фактов в графе"
    assert isinstance(graph["edges"], list), graph["edges"]


@then(parsers.parse('трассировка фактов на источники сохранена'))
def tracing_kept(pg_state):
    from services.extractor.repository import knowledge_repo

    facts = knowledge_repo.get_graph(pg_state["package"])["facts"]
    assert any(
        f.get("doc") is not None and f.get("frag") is not None for f in facts
    ), "у фактов нет источника"


@then(parsers.parse('число подтвержденных фактов пакета "{pid}" не изменилось'))
def confirmed_unchanged(pg_state, pid):
    from contracts.ontology import LifecycleStatus
    from services.extractor.repository import knowledge_repo

    confirmed = knowledge_repo.count_by_status(
        pid, LifecycleStatus.CONFIRMED.value
    )
    assert confirmed == pg_state["facts_before"], (confirmed, pg_state["facts_before"])
