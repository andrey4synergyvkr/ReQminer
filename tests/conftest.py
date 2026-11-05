import json
import logging
import shutil
from pathlib import Path

import pytest

from demo.scenario import DEMO_PACKAGE, EXPECTED_METRICS
from services.common import llm_cache
from services.common.llm_adapter import reset_adapter
from services.extractor.repository import knowledge_repo
from services.ingestor import scanner
from services.ingestor.chunker import chunk_markdown, chunk_plain
from services.ingestor.repository import chunks_repo

logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

PACKAGE_ID = DEMO_PACKAGE

SAMPLE_DOCUMENTS = {
    "tz.md": (
        "# Техническое задание\n\n"
        "## Цели проекта\n\n"
        "Система должна автоматизировать обработку обращений граждан.\n\n"
        "## Сроки и ограничения\n\n"
        "Внедрение должно быть завершено в срок до 3 месяцев. "
        "Бюджет проекта не более 2 млн руб.\n"
    ),
    "feature_request.md": (
        "# Пожелания\n\n"
        "Хотим экспорт отчета в XLSX, чтобы передавать данные заказчику.\n"
    ),
    "correspondence.md": (
        "# Переписка\n\n"
        "- Бюджет проекта не более 2 млн руб.\n"
        "- Указан срок внедрения 6 месяцев.\n"
        "- Время обработки пакета до 30 минут.\n"
    ),
    "scan.pdf": "не текстовый документ",
}


@pytest.fixture(autouse=True)
def clean_storage(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("NEO4J_URI", "")
    from services.common import db as db_mod, graph_db as graph_db_mod

    db_mod.reset_engine()
    graph_db_mod.reset_driver()
    chunks_repo.reset_backend()
    knowledge_repo.reset_backend()
    from services.orchestrator import registry as registry_mod

    registry_mod.reset_backend()
    chunks_repo.reset()
    knowledge_repo.reset()
    reset_adapter()
    llm_cache.reset()
    yield
    chunks_repo.reset()
    knowledge_repo.reset()
    reset_adapter()
    llm_cache.reset()
    db_mod.reset_engine()
    graph_db_mod.reset_driver()
    chunks_repo.reset_backend()
    knowledge_repo.reset_backend()
    registry_mod.reset_backend()


@pytest.fixture
def state() -> dict:
    return {}


@pytest.fixture
def outbox_root(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "outbox"
    monkeypatch.setenv("OUTBOX_ROOT", str(root))
    return root


@pytest.fixture
def demo_metrics() -> dict:
    return dict(EXPECTED_METRICS)


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    pkg = tmp_path / PACKAGE_ID
    pkg.mkdir()
    for name, content in SAMPLE_DOCUMENTS.items():
        (pkg / name).write_text(content, encoding="utf-8")
    return tmp_path


@pytest.fixture
def empty_inbox(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def package_result(inbox: Path):
    return scanner.process_package(PACKAGE_ID, inbox / PACKAGE_ID)


@pytest.fixture
def chunking(inbox: Path):
    doc = inbox / PACKAGE_ID / "tz.md"
    return {"doc": doc.name, "content": doc.read_text(encoding="utf-8")}


@pytest.fixture
def chunks(chunking):
    return chunk_markdown(chunking["doc"], chunking["content"])
