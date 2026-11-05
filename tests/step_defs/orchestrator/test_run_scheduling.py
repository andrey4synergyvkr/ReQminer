from __future__ import annotations

import time

from orchestrator_steps import *  # noqa: F401,F403
from orchestrator_steps import PACKAGE
from pytest_bdd import scenarios, then

from services.extractor.repository import knowledge_repo
from services.ingestor.repository import chunks_repo

scenarios("../../features/orchestrator/run_scheduling.feature")


@then('команда принята сразу, не дожидаясь завершения конвейера')
def accepted_immediately(state):
    assert state["accepted"] is True
    assert time.monotonic() - state["submitted_at"] < 1.0


@then('команда отклонена')
def command_rejected(state):
    assert state["accepted"] is False


@then('новые фрагменты в Chunks не созданы')
def no_new_fragments(state):
    assert chunks_repo.stats(PACKAGE)["fragments"] == state["fragments_before"]


@then('новые факты в Knowledge не созданы')
def no_new_facts(state):
    assert knowledge_repo.facts_total(PACKAGE) == state["facts_before"]
