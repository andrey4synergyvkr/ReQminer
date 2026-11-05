from __future__ import annotations

import time

import pytest
from pytest_bdd import given, parsers, step, then, when

from services.extractor.repository import knowledge_repo
from services.ingestor.repository import chunks_repo
from services.orchestrator import registry, scheduler

PACKAGE = "2026-050"


@pytest.fixture(autouse=True)
def reset_scheduler_state(tmp_path):
    with scheduler._lock:
        scheduler._active.clear()
    registry.reset_backend()
    registry.configure(tmp_path, force=True)
    yield
    with scheduler._lock:
        scheduler._active.clear()

_REQ_DOC = "tz.md"
_REQ_FRAGMENTS = [
    "Как аналитик, я хочу загружать входящие документы.",
    "Время отклика интерфейса не должно превышать двух секунд.",
]
_NO_REQ_FRAGMENTS = [
    "Команда проекта подтверждает готовность к старту работ.",
]

_WAIT_TIMEOUT = 30.0


def _register_package(pid: str, docs: dict[str, str],
                      files: list[dict] | None = None) -> None:
    staged = [
        {
            "name": name,
            "type": "не определен",
            "content": content.encode("utf-8"),
        }
        for name, content in docs.items()
    ]
    registry.create_package(f"Пакет {pid}", "обращение заказчика", staged, pid=pid)
    if files is not None:
        pkg = registry.get_package(pid)
        pkg["files"] = files
        registry.update_package(pid, files=files)
    chunks_repo.reset(pid)
    knowledge_repo.reset(pid)


def wait_run(pid: str, timeout: float = _WAIT_TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = registry.get_run(pid)
        if run and run.get("state") not in ("run", None):
            return run
        time.sleep(0.05)
    raise TimeoutError(f"прогон {pid} не завершился за {timeout} с")


@given(parsers.parse('пакет "{pid}" зарегистрирован с документом "{doc}" в inbox'))
def package_with_doc(state, pid, doc):
    state["package"] = pid
    _register_package(pid, {doc: "\n".join(_REQ_FRAGMENTS) + "\n"})


@given(parsers.parse('пакет "{pid}" зарегистрирован с документами {docs} в inbox'))
def package_with_docs(state, pid, docs):
    names = [
        p.strip().strip('"') for p in docs.replace('" и "', '", "').split(", ")
    ]
    contents = {
        "tz.md": "\n".join(_REQ_FRAGMENTS) + "\n",
        "scan.pdf": "не текстовый документ",
        "note.docx": "документ недопустимого формата",
    }
    ok_docs = {n: contents[n] for n in names if n != "note.docx"}
    state["package"] = pid
    _register_package(pid, ok_docs)
    pkg = registry.get_package(pid)
    if "note.docx" in names:
        pkg_files = pkg["files"] + [{"name": "note.docx", "verdict": "reject"}]
        registry.update_package(pid, files=pkg_files)


@given(parsers.parse('фрагменты документа "{doc}" не содержат требований'))
def fragments_without_requirements(state, doc):
    _register_package(state["package"], {doc: "\n".join(_NO_REQ_FRAGMENTS) + "\n"})


@given(parsers.parse('прогон пакета "{pid}" выполняется'))
def run_in_progress(state, pid, monkeypatch):
    with scheduler._lock:
        scheduler._active.add(pid)


@given(parsers.parse('пакет "{pid}" уже прогнан'))
def package_already_run(state, pid):
    _register_package(pid, {_REQ_DOC: "\n".join(_REQ_FRAGMENTS) + "\n"})
    scheduler.submit(pid)
    state["first"] = wait_run(pid)
    state["fragments_before"] = chunks_repo.stats(pid)["fragments"]
    state["facts_before"] = knowledge_repo.facts_total(pid)


@given(parsers.parse('пакет "{pid}" отклонен по формату'))
def package_rejected(state, pid):
    state["package"] = pid
    registry.create_package(
        f"Пакет {pid}", "обращение заказчика",
        [{"name": "scan.pdf", "type": "не определен",
          "content": "не текстовый документ".encode("utf-8")}],
        pid=pid,
    )


@given('сервис Extractor падает с ошибкой')
def extractor_fails(monkeypatch):
    from services.extractor import service as extractor_service

    def boom(package, **kwargs):
        raise RuntimeError("сбой извлечения фактов")

    monkeypatch.setattr(extractor_service, "extract_facts", boom)


@when('аналитик запускает анализ пакета')
def submit_run(state):
    pid = state["package"]
    state["submitted_at"] = time.monotonic()
    state["accepted"] = scheduler.submit(pid)


@when('аналитик повторно запускает анализ пакета')
def resubmit_run(state):
    state["accepted"] = scheduler.submit(state["package"])


@step('прогон пакета завершается в фоне')
def wait_background_run(state):
    state["run"] = wait_run(state["package"])


@then('все этапы конвейера завершены')
def all_stages_done(state):
    stages = state["run"]["stages"]
    assert len(stages) == 4, stages
    assert all(s["status"] == "done" for s in stages), stages
