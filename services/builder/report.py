from __future__ import annotations

from services.builder.planner import TEMPLATE_SET
from services.common.formats import format_ts


def build_report(package: str, metrics: dict, gaps: str | None,
                 prompt_version: str | None = None) -> str:
    """Формирует analysis_report.md: метрики прогона и пробелы модели.

    prompt_version передаётся только для облачного прогона: отчёт фиксирует
    формулировки, на которых получены тексты разделов. В offline-режиме
    промптов нет, поэтому отчёт не меняется.
    """
    return TEMPLATE_SET.render(
        "documents/analysis_report.md.j2",
        package=package, metrics=metrics, gaps=gaps,
        prompt_version=prompt_version,
        generated=format_ts(),
    )
