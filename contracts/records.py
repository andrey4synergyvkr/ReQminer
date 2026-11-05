from __future__ import annotations

from typing import TypedDict

from contracts.ontology import LifecycleStatus

DEFAULT_CONFIDENCE = 0.5


class Fact(TypedDict, total=False):
    """Проекция требования для Extractor/UI/Builder."""

    id: str
    type: str
    title: str
    confidence: float
    status: str
    doc: str | None
    frag: int | None
    package: str
    definition: str
    raw_snippet: str
    reviewed_by: str
    validated_at: str


class Pair(TypedDict, total=False):
    """Пара-кандидат противоречия или дубликата."""

    id: str
    kind: str
    reason: str
    a: str
    b: str
    status: str


class Package(TypedDict, total=False):
    """Строка реестра пакетов."""

    id: str
    name: str
    direction: str
    documents: int
    status: str
    facts: int | None
    last_run: str
    started: str
    reject_reason: str | None
    files: list[dict]


class Stage(TypedDict, total=False):
    """Этап конвейера в записи прогона."""

    service: str
    mod: str
    status: str
    processed: str
    done: int
    total: int
    unit: str


class Progress(TypedDict, total=False):
    """Прогресс прогона: фаза, процент, счётчик единиц и оценка остатка."""

    phase: str
    phase_index: int
    phases_total: int
    percent: int
    done: int
    total: int
    unit: str
    detail: str
    eta_seconds: int
    updated: str


class Metrics(TypedDict, total=False):
    """Метрики прогона (Builder, экраны, сид)."""

    documents: int
    fragments: int
    facts: int
    confirmed: int
    pending: int
    pairs_contradiction: int
    pairs_duplicate: int
    quarantine: int
    llm_retries: int


class Run(TypedDict, total=False):
    """Запись прогона пакета."""

    state: str
    started: str
    finished: str
    stages: list[Stage]
    metrics: Metrics
    progress: Progress
    error: str


class GraphNode(TypedDict, total=False):
    """Узел графа требований для экрана и API."""
    id: str
    kind: str
    type: str
    title: str
    doc: str
    frag: int
    label: str


class GraphEdge(TypedDict, total=False):
    """Ребро графа: тип связи и её концы."""
    source: str
    target: str
    type: str


class Graph(TypedDict, total=False):
    """Граф требований: сырые факты/ребра или UI-проекция для app.js."""

    package: str
    facts: list[Fact]
    nodes: list[GraphNode]
    edges: list[GraphEdge]


_REQUIRED_FACT_FIELDS = ("title", "type", "status")


def normalize_fact(fact: Fact) -> Fact:
    """Граница записи факта: обязательные поля и null-уверенность > 0.5."""

    missing = [name for name in _REQUIRED_FACT_FIELDS if not fact.get(name)]
    if missing:
        raise ValueError(
            "факт без обязательных полей: " + ", ".join(missing)
        )
    if fact.get("confidence") is None:
        fact["confidence"] = DEFAULT_CONFIDENCE
    return fact


def lifecycle_value(status: LifecycleStatus | str) -> str:
    """Значение LifecycleStatus из enum или строки; недопустимое - ValueError."""
    return LifecycleStatus(status).value
