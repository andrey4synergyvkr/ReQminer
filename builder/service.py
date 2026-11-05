from __future__ import annotations

import time

from services.builder.generator import generate
from services.builder.planner import OUTBOX_SECTIONS, gaps, gaps_text, plan
from services.builder.prompts import builder_prompts
from services.builder.report import build_report
from services.builder.writer import read as _read
from services.builder.writer import write as _write
from services.builder.writer import zip_package as _zip_package
from services.common.llm_adapter import get_adapter
from services.common.logging import get_logger
from services.common.progress import ProgressTick

log = get_logger("builder.service")

__all__ = [
    "OUTBOX_SECTIONS",
    "build",
    "export_zip",
    "gaps_text",
    "get_doc",
]


def build(package: str, facts: list[dict], metrics: dict,
          *, progress: ProgressTick | None = None) -> dict[str, str]:
    """Формирует и записывает каркас: {относительный путь: markdown-текст}."""
    started = time.monotonic()
    sections = plan(facts)
    docs = generate(sections, progress=progress)
    adapter = get_adapter()
    # версия промптов - только для текстов модели: в offline-режиме
    # разделы детерминированы, и отчет остается прежним
    docs["analysis_report.md"] = build_report(
        package, metrics, gaps(facts),
        prompt_version=builder_prompts.version() if adapter.mode == "cloud" else None,
    )
    if progress is not None:
        # генератор считает отчет последней единицей фазы (total = разделы + 1)
        total = sum(1 for section in sections.values() if section["facts"]) + 1
        progress(total, total, "analysis_report.md")
    _write(package, docs)
    log.info(
        "Builder %s: каркас из %d файлов (%d разделов с фактами из %d) за %.1f с",
        package, len(docs),
        sum(1 for s in sections.values() if s["facts"]),
        len(facts), time.monotonic() - started,
    )
    return docs


def get_doc(package: str, rel_path: str) -> str | None:
    """Читает файл каркаса; rel_path ограничен корнем outbox пакета."""
    return _read(package, rel_path)


def export_zip(package: str) -> bytes:
    """Экспорт каркаса пакета в zip (в памяти)."""
    return _zip_package(package)
