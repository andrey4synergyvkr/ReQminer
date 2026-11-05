from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from contracts.records import Fact, Metrics, Package, Run, Stage
from contracts.stores import KnowledgeStore, SeedableChunkStore, SeedableRunStore
from contracts.workflow import (
    FileVerdict,
    PackageStatus,
    RunState,
    StageStatus,
)
from demo.scenario import DEMO_PACKAGE, DEMO_QUARANTINE
from services.builder import service as builder
from services.common.formats import format_ts
from services.common.logging import get_logger
from services.common.progress import ProgressTick
from services.extractor import service as extractor
from services.extractor.repository import knowledge_repo
from services.extractor.service import ExtractResult, PairResult
from services.ingestor import scanner
from services.ingestor.repository import chunks_repo
from services.orchestrator import registry
from services.orchestrator.metrics import collect
from services.orchestrator.progress import PHASE_DEFS, ProgressReporter

log = get_logger("orchestrator.pipeline")


@dataclass(frozen=True)
class PipelineServices:
    """Внедряемые зависимости одного прогона."""

    chunks: SeedableChunkStore
    knowledge: KnowledgeStore
    registry: SeedableRunStore
    extract_facts: Callable[..., ExtractResult]
    detect_pairs: Callable[..., PairResult]
    build: Callable[..., dict]


@dataclass
class RunContext:
    """Состояние, общее для шагов одного прогона."""

    pid: str
    pkg: Package
    run: Run
    services: PipelineServices
    progress: ProgressReporter | None = None
    pairs: int = 0


@dataclass(frozen=True)
class PipelineStep:
    """Этап конвейера: подпись для UI и обработчик."""

    service: str
    mod: str
    handler: Callable[[RunContext], str]


def _default_build(pid: str, facts: list[Fact], metrics: Metrics,
                   *, progress: ProgressTick | None = None) -> dict:
    return builder.build(pid, facts, metrics, progress=progress)


def build_services(
    *,
    chunks: SeedableChunkStore | None = None,
    knowledge: KnowledgeStore | None = None,
    registry_service: SeedableRunStore | None = None,
    extractor_service=None,
    builder_service=None,
) -> PipelineServices:
    """Собирает зависимости прогона; без аргументов - глобальные фасады.

    extractor_service - модуль или объект с методами extract_facts и
    detect_pairs; по умолчанию используется services.extractor.service.
    """
    extractor_api = extractor_service or extractor
    return PipelineServices(
        chunks=chunks or chunks_repo,
        knowledge=knowledge or knowledge_repo,
        registry=registry_service or registry,
        extract_facts=extractor_api.extract_facts,
        detect_pairs=extractor_api.detect_pairs,
        build=builder_service or _default_build,
    )


def stage(index: int, status: StageStatus, processed: str) -> Stage:
    """Запись этапа для формы прогресса."""
    definition = PHASE_DEFS[index]
    return {
        "service": definition.service,
        "mod": definition.mod,
        "status": status.value,
        "processed": processed,
        "done": 0,
        "total": 0,
        "unit": definition.unit,
    }


def _tick(ctx: RunContext) -> ProgressTick | None:
    """Колбэк прогресса для сервиса; без reporter-а (сиды, тесты) - None."""
    return ctx.progress.tick if ctx.progress is not None else None


# --- обработчики этапов -----------------------------------------------------

def _ingest(ctx: RunContext) -> str:
    pid = ctx.pid
    services = ctx.services
    ing = scanner.process_package(
        pid, services.registry.inbox_dir(pid), chunks=services.chunks,
        progress=_tick(ctx),
    )
    if ing.documents == 0 and pid == DEMO_PACKAGE:
        # у пакета контрольного примера документов в inbox нет - берутся
        # сидированные фрагменты; произвольный пустой пакет остаётся пустым
        log.debug("Прогон %s: inbox пуст — фрагменты из сида Chunks", pid)
        services.chunks.seed_demo(pid)

    stats = services.chunks.stats(pid)
    ctx.run["metrics"]["fragments"] = stats["fragments"]
    ctx.run["metrics"]["documents"] = stats["documents"]

    # карантин: отклонения сканера плюс отклонения формы, без двойного счёта
    form_rejected = {
        f["name"] for f in ctx.pkg.get("files", [])
        if f.get("verdict") == FileVerdict.REJECT.value
    }
    ctx.run["metrics"]["quarantine"] = (
        DEMO_QUARANTINE if pid == DEMO_PACKAGE and ing.documents == 0
        else len(set(ing.rejected) | form_rejected)
    )
    return f"{stats['documents']} документа, {stats['fragments']} фрагментов"


def _extract(ctx: RunContext) -> str:
    services = ctx.services
    result = services.extract_facts(
        ctx.pid, knowledge=services.knowledge, chunks=services.chunks,
        progress=_tick(ctx),
    )
    ctx.run["metrics"]["facts"] = result.facts
    ctx.run["metrics"]["llm_retries"] = result.llm_retries
    return (
        f"{result.fragments} из {result.fragments} фрагментов, "
        f"{result.facts} фактов"
    )


def _detect_pairs(ctx: RunContext) -> str:
    services = ctx.services
    result = services.detect_pairs(
        ctx.pid, knowledge=services.knowledge, progress=_tick(ctx)
    )
    ctx.pairs = result.pairs
    ctx.run["metrics"]["llm_retries"] += result.llm_retries
    return f"{result.pairs} пары-кандидата"


def _build(ctx: RunContext) -> str:
    services = ctx.services
    # метрики до Builder: analysis_report.md получает confirmed/pending/пары
    facts = services.knowledge.list_facts(ctx.pid)
    pairs = services.knowledge.pairs_of(ctx.pid)
    ctx.run["metrics"] = collect(
        ctx.pid, ctx.run["metrics"], facts=facts, pairs=pairs
    )
    docs = services.build(
        ctx.pid, facts, ctx.run["metrics"], progress=_tick(ctx)
    )
    return f"{len(docs)} разделов каркаса"


_HANDLERS = (_ingest, _extract, _detect_pairs, _build)

PIPELINE_STEPS = tuple(
    PipelineStep(definition.service, definition.mod, handler)
    for definition, handler in zip(PHASE_DEFS, _HANDLERS)
)

# Совместимость с прежним публичным именем (runner.STAGE_DEFS).
STAGE_DEFS = [(step.service, step.mod) for step in PIPELINE_STEPS]


# --- жизненный цикл прогона -------------------------------------------------

def start_run(registry_service: SeedableRunStore, pid: str, pkg: Package) -> Run:
    """Создаёт запись прогона и переводит пакет в состояние run."""
    now = datetime.now()
    run: Run = {
        "state": RunState.RUN.value,
        "started": now.isoformat(timespec="seconds"),
        "stages": [
            stage(index, StageStatus.WAIT, "—")
            for index in range(len(PIPELINE_STEPS))
        ],
        "metrics": {"fragments": 0, "facts": 0, "llm_retries": 0, "quarantine": 0},
        "progress": {
            "phase": PHASE_DEFS[0].phase.value,
            "phase_index": 0,
            "phases_total": len(PHASE_DEFS),
            "percent": 0,
            "done": 0,
            "total": 0,
            "unit": PHASE_DEFS[0].unit,
            "detail": "",
            "eta_seconds": -1,
            "updated": now.isoformat(timespec="seconds"),
        },
        "finished": "",
    }
    registry_service.set_run(pid, run)
    registry_service.update_package(
        pid, status=PackageStatus.RUN.value, facts=None, started=run["started"]
    )
    return run


def mark_failed(run: Run, exc: Exception) -> None:
    """Помечает упавший этап и оставляет последующие не начатыми."""
    run["state"] = RunState.FAILED.value
    run["error"] = str(exc)
    run["stages"] = [
        {**s, "status": StageStatus.FAILED.value, "processed": str(exc)}
        if s["status"] == StageStatus.RUN.value
        else s if s["status"] == StageStatus.DONE.value
        else {**s, "status": StageStatus.WAIT.value, "processed": "—"}
        for s in run["stages"]
    ]


def finish_run(registry_service: SeedableRunStore, pid: str, run: Run) -> None:
    """Фиксирует время завершения и итоговый статус пакета."""
    run["finished"] = format_ts()
    registry_service.set_run(pid, run)
    package_status = (
        PackageStatus.DONE if run["state"] == RunState.DONE
        else PackageStatus.CONFIRM if run["state"] == RunState.CONFIRM
        else PackageStatus.FAILED
    )
    registry_service.update_package(
        pid,
        status=package_status.value,
        facts=run["metrics"]["facts"] or None,
        last_run=run["finished"],
    )
    log.info(
        "Прогон %s завершен: %s (фактов %d, карантин %d)",
        pid, run["state"], run["metrics"]["facts"], run["metrics"]["quarantine"],
    )
