from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from contracts.ontology import LifecycleStatus
from contracts.workflow import PairAction, PairKind, PairStatus

# Статусы, которые детектор не имеет права переписывать: это уже решение
# человека или завершённая работа, а не кандидат на уточнение.
TERMINAL_STATUSES = frozenset({
    LifecycleStatus.CONFIRMED.value,
    LifecycleStatus.REJECTED.value,
    LifecycleStatus.APPROVED.value,
    LifecycleStatus.DONE.value,
    LifecycleStatus.DEPRECATED.value,
})


@dataclass(frozen=True)
class PairResolution:
    """Результат решения аналитика: статус пары и изменения фактов."""

    pair_status: str
    statuses: dict[str, str]
    mark_reviewed: bool = False


@dataclass(frozen=True)
class PairActionRule:
    """Строка таблицы действий: статус пары, изменения фактов, отметка."""

    pair_status: str
    statuses: Callable[[dict, dict], dict[str, str]]
    mark_reviewed: bool = False


def _keep_and_duplicate(a: dict, b: dict) -> tuple[dict, dict]:
    """Победитель и дубликат: при равной уверенности побеждает факт a."""
    if (a.get("confidence") or 0) >= (b.get("confidence") or 0):
        return a, b
    return b, a


def _is_mutable(fact: dict) -> bool:
    return fact.get("status") not in TERMINAL_STATUSES


def _contradiction_cascade(a: dict, b: dict) -> dict[str, str]:
    return {
        fact["id"]: LifecycleStatus.NEEDS_CLARIFICATION.value
        for fact in (a, b)
        if _is_mutable(fact)
    }


def _duplicate_cascade(a: dict, b: dict) -> dict[str, str]:
    _, duplicate = _keep_and_duplicate(a, b)
    if _is_mutable(duplicate):
        return {duplicate["id"]: LifecycleStatus.DUPLICATE.value}
    return {}


CASCADE_RULES: dict[str, Callable[[dict, dict], dict[str, str]]] = {
    PairKind.CONTRADICTION: _contradiction_cascade,
    PairKind.DUPLICATE: _duplicate_cascade,
}


def _duplicate_decision(a: dict, b: dict) -> dict[str, str]:
    keep, duplicate = _keep_and_duplicate(a, b)
    return {
        keep["id"]: LifecycleStatus.CONFIRMED.value,
        duplicate["id"]: LifecycleStatus.DUPLICATE.value,
    }


def _contradiction_decision(a: dict, b: dict) -> dict[str, str]:
    status = LifecycleStatus.NEEDS_CLARIFICATION.value
    return {a["id"]: status, b["id"]: status}


def _dismiss_decision(a: dict, b: dict) -> dict[str, str]:
    status = LifecycleStatus.PENDING_REVIEW.value
    return {a["id"]: status, b["id"]: status}


PAIR_ACTIONS: dict[str, PairActionRule] = {
    PairAction.DUPLICATE: PairActionRule(
        pair_status=PairStatus.DUPLICATE.value,
        statuses=_duplicate_decision,
        mark_reviewed=True,
    ),
    PairAction.CONTRADICTION: PairActionRule(
        pair_status=PairStatus.CONTRADICTION.value,
        statuses=_contradiction_decision,
        mark_reviewed=True,
    ),
    PairAction.DISMISS: PairActionRule(
        pair_status=PairStatus.DISMISS.value,
        statuses=_dismiss_decision,
    ),
}


def detector_cascade(kind: str, a: dict, b: dict) -> dict[str, str]:
    """Статусы фактов по вердикту детектора: {fact_id: новый статус}."""
    rule = CASCADE_RULES.get(kind)
    return rule(a, b) if rule is not None else {}


def resolve_pair(action: str, a: dict, b: dict) -> PairResolution | None:
    """Решение аналитика по паре; неизвестное действие - None (отказ)."""
    rule = PAIR_ACTIONS.get(action)
    if rule is None:
        return None
    return PairResolution(
        pair_status=rule.pair_status,
        statuses=rule.statuses(a, b),
        mark_reviewed=rule.mark_reviewed,
    )
