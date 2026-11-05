from __future__ import annotations

from orchestrator_steps import *  # noqa: F401,F403
from pytest_bdd import parsers, scenarios, then

from services.orchestrator import registry

scenarios("../../features/orchestrator/run_registry.feature")


@then('запись прогона доступна в реестре')
def run_in_registry(state):
    run = registry.get_run(state["package"])
    assert run is not None


@then('запись содержит этапы и метрики')
def run_has_stages_and_metrics(state):
    run = registry.get_run(state["package"])
    assert run["stages"] and len(run["stages"]) == 4
    assert "facts" in run["metrics"]


@then(parsers.parse('статус пакета в реестре "{status}"'))
def package_status(state, status):
    pkg = registry.get_package(state["package"])
    assert pkg["status"] == status, pkg["status"]
