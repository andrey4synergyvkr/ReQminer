from __future__ import annotations

from contracts.ontology import LifecycleStatus
from contracts.records import Fact, Metrics, Pair
from contracts.workflow import PairKind
from services.extractor.repository import knowledge_repo


def collect(
    pid: str,
    base: dict | None = None,
    *,
    facts: list[Fact] | None = None,
    pairs: list[Pair] | None = None,
) -> Metrics:
    """Дополняет базовые метрики счётчиками фактов и пар из снимка."""
    if facts is None:
        facts = knowledge_repo.list_facts(pid)
    if pairs is None:
        pairs = knowledge_repo.pairs_of(pid)
    metrics: Metrics = dict(base or {})
    metrics.update({
        "facts": len(facts),
        "confirmed": sum(
            1 for f in facts if f["status"] == LifecycleStatus.CONFIRMED.value
        ),
        "pending": sum(
            1 for f in facts if f["status"] == LifecycleStatus.PENDING_REVIEW.value
        ),
        "pairs_contradiction": sum(
            1 for p in pairs if p["kind"] == PairKind.CONTRADICTION
        ),
        "pairs_duplicate": sum(
            1 for p in pairs if p["kind"] == PairKind.DUPLICATE
        ),
    })
    return metrics
