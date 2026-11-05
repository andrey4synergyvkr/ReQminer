from __future__ import annotations

import hashlib
import json

from pytest_bdd import given, parsers, when
from services.common import llm_adapter as adapter_module
from services.common.llm_adapter import OfflineLlmAdapter, reset_adapter
from services.extractor import service as extractor_service
from services.extractor.repository import knowledge_repo
from services.ingestor.repository import chunks_repo
from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact

PACKAGE = "2026-042"

STANDARD_FRAGMENTS = [
    "Как аналитик, я хочу загружать входящие документы.",
    "Время отклика интерфейса не должно превышать двух секунд.",
    "Срок внедрения системы — не позднее трёх месяцев с даты подписания договора.",
    "Система должна обеспечивать интеграцию с корпоративной системой документооборота.",
    "Функциональность «Пакетный приём документов»: приём группы документов одной операцией.",
    "Эпик — крупная функциональная цель, объединяющая несколько функций системы.",
    "Стратегическая цель — единая точка приёма требований от всех заказчиков.",
    "Как аналитик, я хочу фильтровать факты по типу и статусу.",
    "Как руководитель, я хочу видеть статистику по обращениям.",
]


def save_doc(package: str, doc: str, fragments: list[str]) -> None:
    artifact = SourceArtifact(
        id=f"{package}:{doc}",
        file_path=f"inbox/{package}/{doc}",
        file_name=doc,
        parsing_status=ParsingStatus.PARSED,
        total_chunks=len(fragments),
    )
    chunks = []
    for i, text in enumerate(fragments, 1):
        chunks.append(DocumentChunk(
            id=f"{package}:{doc}:{i}",
            chunk_index=i,
            content=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            start_offset=0,
            end_offset=len(text),
            token_count=len(text) // 4,
            metadata=json.dumps({"doc": doc}),
        ))
    chunks_repo.save(package, artifact, chunks)


def reset_package_fragments(fragments: list[str], doc: str = "tz.md") -> None:
    chunks_repo.reset(PACKAGE)
    knowledge_repo.reset(PACKAGE)
    save_doc(PACKAGE, doc, fragments)


class ScriptedAdapter(OfflineLlmAdapter):

    def __init__(self, candidates_per_fragment: list[list[dict]] | None = None,
                 unknown_candidate: dict | None = None) -> None:
        super().__init__()
        self._scripted = candidates_per_fragment
        self._unknown = unknown_candidate
        self._marker: list[int] = []

    def extract_candidates(self, fragment_text: str) -> list[dict]:
        if self._scripted is not None:
            index = min(len(self._marker), len(self._scripted) - 1)
            self._marker.append(1)
            return self._scripted[index]
        if self._unknown is not None:
            return [self._unknown]
        return super().extract_candidates(fragment_text)


class FlakyCloudAdapter(adapter_module.CloudLlmAdapter):

    def __init__(self, failures: int, answer: str) -> None:
        adapter_module._BaseAdapter.__init__(self, mode="cloud")
        self._failures = failures
        self._answer = answer

    def _ask(self, system: str, user: str) -> str:
        if self._failures > 0:
            self._failures -= 1
            raise ConnectionError("сбой провайдера")
        return self._answer


@given(parsers.parse('пакет "{package}" обработан Ingestor-ом и содержит фрагменты в Chunks'))
def package_ingested(state, package):
    state["package"] = package.split()[-1]
    reset_package_fragments(STANDARD_FRAGMENTS)


@given('LlmAdapter отвечает заданными кандидатами требований')
def llm_adapter_ready():
    reset_adapter()


@given(parsers.parse('Extractor извлек факты и все они в статусе "{status}"'))
def facts_extracted(state, status):
    state["package"] = PACKAGE
    reset_package_fragments(STANDARD_FRAGMENTS)
    extractor_service.extract(PACKAGE)
    assert knowledge_repo.facts_total(PACKAGE) >= 2
    assert knowledge_repo.pending_count(PACKAGE) == knowledge_repo.facts_total(PACKAGE)


@given(parsers.parse('пакет "{package}" уже обработан Extractor-ом'))
def package_extracted(state, package):
    state["package"] = package.split()[-1]
    reset_package_fragments(STANDARD_FRAGMENTS)
    state["facts_before"] = extractor_service.extract(PACKAGE).facts


@when('Extractor обрабатывает пакет')
def extract_package(state):
    state["result"] = extractor_service.extract(state["package"])


@when('Extractor повторно обрабатывает тот же пакет')
def extract_package_again(state):
    state["result"] = extractor_service.extract(state["package"])
