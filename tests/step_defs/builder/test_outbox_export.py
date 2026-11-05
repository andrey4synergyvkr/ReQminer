from __future__ import annotations

import io
import zipfile

from builder_steps import *  # noqa: F401,F403
from pytest_bdd import parsers, scenarios, then, when

from services.builder import service as builder

scenarios("../../features/builder/outbox_export.feature")


@when('Builder сохраняет каркас в outbox')
def save_to_outbox(state, demo_metrics):
    state["docs"] = builder.build(state["package"], state["facts"], demo_metrics)


@when('аналитик запрашивает экспорт каркаса')
def export_skeleton(state):
    state["zip_bytes"] = builder.export_zip(state["package"])


@when(parsers.parse('аналитик открывает файл "{path}"'))
def open_doc(state, path):
    state["opened"] = builder.get_doc(state["package"], path)


@then('в outbox созданы файлы vision_and_strategy.md, glossary.md и constraints.md')
def files_created(state, outbox_root):
    pkg = outbox_root / state["package"]
    for name in ("vision_and_strategy.md", "glossary.md", "constraints.md"):
        assert (pkg / name).is_file(), name


@then('созданы подкаталоги functional_reqs и non_functional_reqs со своими файлами')
def dirs_created(state, outbox_root):
    pkg = outbox_root / state["package"]
    for rel in (
        "functional_reqs/epics.md",
        "functional_reqs/features.md",
        "functional_reqs/user_stories.md",
        "non_functional_reqs/quality_goals.md",
    ):
        assert (pkg / rel).is_file(), rel


@then('создан файл analysis_report.md')
def report_created(state, outbox_root):
    assert (outbox_root / state["package"] / "analysis_report.md").is_file()


@then('zip-архив содержит все файлы каркаса')
def zip_contains_all(state):
    with zipfile.ZipFile(io.BytesIO(state["zip_bytes"])) as archive:
        assert sorted(archive.namelist()) == sorted(state["docs"])


@then('содержимое файла возвращено для предпросмотра')
def doc_returned(state):
    expected = state["docs"]["functional_reqs/user_stories.md"]
    assert state["opened"] == expected


@then('доступ к файлу отклонен')
def access_denied(state):
    assert state["opened"] is None
