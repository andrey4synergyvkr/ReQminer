from __future__ import annotations

import time

from contracts.records import Run
from contracts.workflow import PackageStatus, RunState
from services.common.logging import get_logger
from services.orchestrator.pipeline import (
    PIPELINE_STEPS, RunContext, build_services, finish_run,
    mark_failed, start_run,
)
from services.orchestrator.progress import PHASE_DEFS, ProgressReporter

log = get_logger("orchestrator.runner")


def run_package(
    pid: str,
    *,
    chunks=None,
    knowledge=None,
    registry_service=None,
    extractor_service=None,
    builder_service=None,
) -> Run | None:
    """Выполняет прогон пакета; возвращает запись прогона из реестра.

    Без аргументов используются глобальные фасады; тесты могут передать
    свои хранилища, реестр, extractor и builder.
    """
    services = build_services(
        chunks=chunks,
        knowledge=knowledge,
        registry_service=registry_service,
        extractor_service=extractor_service,
        builder_service=builder_service,
    )
    pkg = services.registry.get_package(pid)
    if pkg is None or pkg["status"] == PackageStatus.REJECT:
        return services.registry.get_run(pid)

    log.info("Прогон %s запущен (пакет «%s»)", pid, pkg["name"])
    run = start_run(services.registry, pid, pkg)
    reporter = ProgressReporter(pid, run, services.registry)
    context = RunContext(pid=pid, pkg=pkg, run=run, services=services, progress=reporter)

    try:
        for index, step in enumerate(PIPELINE_STEPS):
            started = time.monotonic()
            reporter.enter(PHASE_DEFS[index].phase)
            processed = step.handler(context)
            reporter.finish_phase(processed)
            log.info(
                "Прогон %s: этап %d/%d (%s — %s) выполнен за %.1f с",
                pid, index + 1, len(PIPELINE_STEPS), step.service, step.mod,
                time.monotonic() - started,
            )

        # Итог: если есть факты, ожидающие подтверждения, - человеческий контур.
        run["state"] = (
            RunState.CONFIRM.value if run["metrics"]["pending"]
            else RunState.DONE.value
        )
        reporter.finish(run["state"])
    except Exception as exc:  # noqa: BLE001 - этап конвейера упал: фиксируем и даем повторить
        log.warning("Прогон %s упал: %s", pid, exc, exc_info=True)
        mark_failed(run, exc)
        reporter.fail(str(exc))

    finish_run(services.registry, pid, run)
    return run
