from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from services.ingestor import scanner
from services.ingestor.repository import chunks_repo
from tests.conftest import SAMPLE_DOCUMENTS

scenarios("../../features/ingestor/package_intake.feature")


def _pkg_dir(state) -> Path:
    d = state["inbox"] / state["package"]
    d.mkdir(exist_ok=True)
    return d


@given(parsers.parse('каталог inbox содержит пакет "{package}"'))
def package_in_inbox(inbox, state, package):
    state["package"] = package
    state["inbox"] = inbox


@given(parsers.parse('в пакете есть документы {docs}'))
def package_with_docs(state, docs):
    parts = [p.strip().strip('"') for p in docs.replace('" и "', '", "').split(", ")]
    pkg_dir = _pkg_dir(state)
    for name in parts:
        (pkg_dir / name).write_text(SAMPLE_DOCUMENTS[name], encoding="utf-8")
    state["docs"] = parts


@given(parsers.parse('в пакете есть документ {doc}'))
def package_with_doc(state, doc):
    name = doc.strip('"')
    pkg_dir = _pkg_dir(state)
    if name in SAMPLE_DOCUMENTS:
        (pkg_dir / name).write_text(SAMPLE_DOCUMENTS[name], encoding="utf-8")
    else:
        (pkg_dir / name).write_bytes(b"%PDF-1.4 not a document")
    state["docs"] = [name]


@given(parsers.parse('документ {doc} существует, но не читается'))
def unreadable_doc(state, monkeypatch, doc):
    name = doc.strip('"')
    pkg_dir = _pkg_dir(state)
    for other, content in SAMPLE_DOCUMENTS.items():
        if other != name:
            (pkg_dir / other).write_text(content, encoding="utf-8")
    unreadable = pkg_dir / name
    unreadable.write_text(SAMPLE_DOCUMENTS[name], encoding="utf-8")
    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        if self == unreadable:
            raise PermissionError(13, "Access is denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    state["docs"] = [n for n in SAMPLE_DOCUMENTS if n != name]


@when('Ingestor обрабатывает пакет')
def process_package(state):
    state["result"] = scanner.process_package(
        state["package"], state["inbox"] / state["package"]
    )


@then(parsers.parse('для каждого документа создан SourceArtifact со статусом {status}'))
def all_docs_have_status(state, status):
    artifacts = chunks_repo.list_artifacts(state["package"])
    assert len(artifacts) == len(state["docs"])
    for a in artifacts:
        assert a.parsing_status.value == status.strip('"'), a.file_name


@then('содержимое каждого документа прочитано')
def all_docs_content_read(state):
    for name in state["docs"]:
        found = any(
            name in (c.metadata_json or "")
            for c in chunks_repo.list_chunks(state["package"])
        )
        assert found, name


@then(parsers.parse('для документа {doc} создан SourceArtifact со статусом {status}'))
def doc_has_status(state, doc, status):
    name = doc.strip('"')
    status = status.strip('"')
    artifact = chunks_repo.get_artifact(state["package"], name)
    assert artifact is not None, name
    assert artifact.parsing_status.value == status, name


@then('обработка пакета продолжена для остальных документов')
def processing_continued(state):
    result = state["result"]
    rejected = set(result.rejected)
    expected = [d for d in state["docs"] if d not in rejected]
    assert result.documents == len(expected), (result.documents, expected)


@then(parsers.parse('для читаемых документов пакета статус {status}'))
def readable_docs_status(state, status):
    status = status.strip('"')
    readable = [d for d in state["docs"] if d not in state["result"].rejected]
    for name in readable:
        artifact = chunks_repo.get_artifact(state["package"], name)
        assert artifact is not None, name
        assert artifact.parsing_status.value == status, name
