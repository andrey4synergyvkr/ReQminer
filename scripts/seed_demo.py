from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.scenario import DEMO_PACKAGE  # noqa: E402
from services.builder import service as builder  # noqa: E402
from services.builder import writer as outbox_writer  # noqa: E402
from services.common import db, graph_db  # noqa: E402
from services.common.logging import configure, get_logger  # noqa: E402
from services.extractor.repository import knowledge_repo  # noqa: E402
from services.ingestor.repository import chunks_repo  # noqa: E402
from services.orchestrator import registry  # noqa: E402
from services.orchestrator.metrics import collect  # noqa: E402

configure()  # файловый лог logs/reqminer.log - ход сида виден и там
log = get_logger("scripts.seed_demo")

PACKAGE = DEMO_PACKAGE


def _external_active() -> bool:
    """Хотя бы одно внешнее хранилище настроено (env/.env)."""
    return db.database_url() is not None or graph_db.graph_uri() is not None


def _backend_resolved() -> bool:
    """Хотя бы один фасад сел на внешний бэкенд (СУБД доступна)."""
    return (
        chunks_repo.backend_name() != "InMemoryChunkRepository"
        or registry.backend_name() != "InMemoryRegistry"
        or knowledge_repo.backend_name() != "InMemoryKnowledgeRepository"
    )


def seed() -> int:
    """Загружает контрольный пример «2026-042» в персистентные хранилища.

    Работает только при настроенных внешних хранилищах: пустая БД означает
    пустое приложение, автоматических сидов нет. В облачном режиме
    извлечение занимает около девяти минут, в offline - секунды.
    """
    from services.extractor import service as extractor_service

    if not _external_active():
        print(
            "Внешние хранилища не настроены (DATABASE_URL/NEO4J_URI): "
            "демо-режим собирает контрольный пример сам при старте UI."
        )
        return 1

    # фасады определяют бэкенды реальным подключением (WARNING при отказе)
    registry.backend_name()
    chunks_repo.backend_name()
    knowledge_repo.backend_name()
    if not _backend_resolved():
        print("Хранилища недоступны: поднимите контейнеры (make db-up)")
        return 1

    # 1. Реестр: пакеты и прогоны контрольного примера (если таблицы пусты)
    if registry.backend_name() != "InMemoryRegistry":
        registry.load_seeds()
        print("Реестр: сиды packages.json/runs.json загружены (если пусто)")

    # 2. Chunks: фрагменты пакета «2026-042» (идемпотентно)
    if chunks_repo.backend_name() != "InMemoryChunkRepository":
        chunks_repo.seed_demo(PACKAGE)
        stats = chunks_repo.stats(PACKAGE)
        print(
            f"Chunks: сид fragments.json загружен "
            f"({stats['documents']} документа, {stats['fragments']} фрагментов)"
        )
    else:
        print("Chunks: in-memory (DATABASE_URL не настроен) — пропущено")

    # 3. Extractor: извлечение фактов (пустой Knowledge - с нуля;
    # повторный сид идемпотентен дедупом по title/doc/frag)
    if knowledge_repo.facts_total(PACKAGE) == 0:
        print(
            "Extractor: извлечение фактов (LLM-режим из .env; "
            "облако ≈9 минут, offline — секунды)...",
            flush=True,
        )
        result = extractor_service.extract(PACKAGE)
        print(
            f"Extractor: {result.fragments} фрагментов, {result.facts} фактов, "
            f"{result.pairs} пар"
        )
    else:
        print(f"Knowledge: факты уже есть ({knowledge_repo.facts_total(PACKAGE)}), "
              "извлечение пропущено")

    # 4. Builder: каркас в outbox (персистентен на файловой системе)
    root = outbox_writer._root() / PACKAGE
    if not (root.is_dir() and any(root.iterdir())):
        stats = chunks_repo.stats(PACKAGE)
        # карантин контрольного примера: скан-копия, отклоненная на форме
        metrics = collect(PACKAGE, {
            "documents": stats["documents"],
            "fragments": stats["fragments"],
            "quarantine": 1,
        })
        builder.build(PACKAGE, knowledge_repo.list_facts(PACKAGE), metrics)
        print("Builder: каркас записан в outbox")
    else:
        print("Builder: каркас уже в outbox, генерация пропущена")

    print(f"Контрольный пример {PACKAGE} готов: запустите make start")
    return 0


if __name__ == "__main__":
    raise SystemExit(seed())
