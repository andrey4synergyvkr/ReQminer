from __future__ import annotations

import threading

from demo.scenario import DEMO_QUARANTINE
from services.builder import planner as skeleton_planner
from services.builder import service as builder
from services.builder.prompts import builder_prompts
from services.common import settings
from services.common.logging import get_logger
from services.common.prompts import prompts
from services.extractor import service as extractor_service
from services.extractor.repository import knowledge_repo
from services.ingestor.repository import chunks_repo
from services.orchestrator import registry
from services.orchestrator.metrics import collect

from .context import build_default_services, configure_services
from .core import DEFAULT_PACKAGE, UPLOADS_DIR

log = get_logger("web_ui")

_demo_built: set[str] = set()
_demo_lock = threading.Lock()


def demo_mode() -> bool:
    """Демо-режим: ни одного внешнего хранилища не настроено.

    Только в демо-режиме контрольный пример собирается автоматически
    (сиды + извлечение): в персистентном режиме пустая БД означает
    пустое приложение, демо сажается явно (make seed).
    """
    return settings.database_url() is None and settings.neo4j_uri() is None


def _skeleton_exists(package: str) -> bool:
    """Каркас пакета уже в outbox (каркас персистентен наравне с фактами)."""
    from services.builder import writer as outbox_writer

    root = outbox_writer._root() / package
    return root.is_dir() and any(root.iterdir())


def _ensure_demo(package: str) -> None:
    """Сборка демо-пакета: Extractor + Builder один раз, из startup.

    Персистентный режим: факты читаются из Knowledge, каркас - из outbox;
    пустая БД остаётся пустой (контрольный пример сажается make seed).
    """
    with _demo_lock:
        if package != DEFAULT_PACKAGE or package in _demo_built:
            return
        stats = chunks_repo.stats(package)
        if knowledge_repo.facts_total(package) == 0:
            if not demo_mode():
                # персистентный Knowledge пуст - автоматического извлечения нет
                return
            fragments = extractor_service.extract(package).fragments
        else:
            # факты пережили рестарт (Neo4j): метрики - из хранилища
            fragments = stats["fragments"]
        # один снимок фактов и пар на сборку каркаса и метрики
        facts = knowledge_repo.list_facts(package)
        pairs = knowledge_repo.pairs_of(package)
        metrics = collect(package, {
            "documents": stats["documents"],
            "fragments": fragments,
            "quarantine": DEMO_QUARANTINE,
        }, facts=facts, pairs=pairs)
        # каркас персистентен в outbox: генерация не повторяется после рестарта
        if not _skeleton_exists(package):
            builder.build(package, facts, metrics)
        _demo_built.add(package)


def startup() -> None:
    """Точка сборки UI: каталоги, реестр, сиды и демо-конвейер.

    Вызывается из lifespan приложения, а не при импорте модуля: импорт
    адаптера в тестах и скриптах не создаёт каталоги и не пишет данные.
    """
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    configure_services(build_default_services())
    settings.validate()
    prompts.validate()
    builder_prompts.validate()
    registry.configure(UPLOADS_DIR)
    skeleton_planner.validate_config()
    if demo_mode():
        chunks_repo.seed_demo(DEFAULT_PACKAGE)
        _ensure_demo(DEFAULT_PACKAGE)
    log.info(
        "Промпты: Extractor %s, Builder %s",
        prompts.version(), builder_prompts.version(),
    )
    log.info(
        "Хранилище Chunks: %s; реестр: %s; Knowledge: %s",
        chunks_repo.backend_name(), registry.backend_name(),
        knowledge_repo.backend_name(),
    )
