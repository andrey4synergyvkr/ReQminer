from __future__ import annotations

from builder_steps import *  # noqa: F401,F403
from builder_steps import make_fact
from pytest_bdd import given, parsers, scenarios, then

scenarios("../../features/builder/metrics_report.feature")

_METRIC_LABELS = (
    "документов", "фрагментов", "фактов", "подтверждено аналитиком",
    "ожидает подтверждения", "пара противоречий", "пара дубликатов", "карантин",
)


@given(parsers.parse('{without:d} из {total:d} пользовательских историй не имеют критериев приемки'))
def stories_without_acceptance(state, without, total):
    facts = []
    for i in range(1, total + 1):
        extra = {} if i <= without else {"acceptance": f"Критерий приемки {i}"}
        facts.append(make_fact(i, "us", **extra))
    state["facts"] = facts


@then('в каркасе есть файл analysis_report.md')
def report_exists(state):
    assert "analysis_report.md" in state["docs"]


@then('отчет содержит метрики: документы, фрагменты, факты, '
      'подтвержденные аналитиком, ожидающие подтверждения, '
      'пары противоречий, пары дубликатов, карантин')
def report_contains_metrics(state):
    report = state["docs"]["analysis_report.md"]
    for label in _METRIC_LABELS:
        assert label in report, label


@then('в отчете отражен пробел модели: не заданы критерии приемки')
def gap_in_report(state):
    report = state["docs"]["analysis_report.md"]
    assert "не заданы критерии приемки для 4 из 15" in report
