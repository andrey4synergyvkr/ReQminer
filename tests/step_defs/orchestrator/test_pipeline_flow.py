from __future__ import annotations

from orchestrator_steps import *  # noqa: F401,F403
from pytest_bdd import parsers, scenarios, then

scenarios("../../features/orchestrator/pipeline_flow.feature")


@then('метрики прогона заполнены: documents, fragments, facts и quarantine')
def metrics_filled(state):
    metrics = state["run"]["metrics"]
    for key in ("documents", "fragments", "facts", "quarantine"):
        assert key in metrics and metrics[key] >= 0, key


@then(parsers.parse('итоговое состояние прогона "{final}"'))
def final_state(state, final):
    assert state["run"]["state"] == final, state["run"]["state"]


@then(parsers.parse('этап {service} имеет статус "{status}" с текстом ошибки'))
def stage_failed_with_error(state, service, status):
    stages = [s for s in state["run"]["stages"] if s["service"] == service]
    failed = [s for s in stages if s["status"] == status]
    assert failed, state["run"]["stages"]
    assert "сбой извлечения фактов" in failed[0]["processed"]


@then('последующие этапы не начаты')
def later_stages_not_started(state):
    stages = state["run"]["stages"]
    builder_stage = stages[3]
    assert builder_stage["status"] == "wait", builder_stage


@then(parsers.parse('метрика quarantine прогона равна {count:d}'))
def quarantine_metric(state, count):
    assert state["run"]["metrics"]["quarantine"] == count
