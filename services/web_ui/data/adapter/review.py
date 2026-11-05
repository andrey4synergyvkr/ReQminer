from __future__ import annotations

from contracts.ontology import LifecycleStatus
from contracts.workflow import PairStatus

from .context import UiServices, get_services
from .core import USER, resolve_package

# Решения аналитика на форме подтверждения - значения ReviewDecision онтологии
# (approve / reject / needs_clarification).
REVIEW_ACTIONS = {
    "confirm": LifecycleStatus.CONFIRMED.value,
    "reject": LifecycleStatus.REJECTED.value,
    "clarify": LifecycleStatus.NEEDS_CLARIFICATION.value,
}


# Без кнопки: открытие экрана «Противоречия» (меню, рис. 2.14) и переход
# кнопкой «К подтверждению (N)» списка фактов (рис. 2.13).
def review_data(package: str | None = None, *,
                services: UiServices | None = None) -> dict:
    """Данные экрана подтверждения: факты и открытые пары."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    pairs = [
        p for p in services.knowledge.pairs_of(package)
        if p.get("status") == PairStatus.OPEN
    ]
    open_pair_facts = {p["a"] for p in pairs} | {p["b"] for p in pairs}
    deciding = (
        LifecycleStatus.PENDING_REVIEW.value,
        LifecycleStatus.NEEDS_CLARIFICATION.value,
    )
    # один снимок фактов пакета: и список к подтверждению, и карточки пар
    # берутся из него (в Neo4j-режиме get_fact - отдельный запрос на факт)
    facts = services.knowledge.list_facts(package)
    by_id = {f["id"]: f for f in facts}
    pending = [
        dict(f)
        for f in facts
        if f["status"] in deciding and f["id"] not in open_pair_facts
    ]
    pending.sort(key=lambda f: (-f["confidence"], f["id"]))
    pair_rows = [
        {**p, "a_fact": by_id[p["a"]], "b_fact": by_id[p["b"]]}
        for p in pairs
        if p["a"] in by_id and p["b"] in by_id
    ]
    return {"pending": pending, "pairs": pair_rows}


# Кнопки «Подтвердить» / «Отклонить» / «Запросить уточнение» (рис. 2.14, секция фактов).
def review_facts(ids: list[str], action: str,
                 package: str | None = None, *,
                 services: UiServices | None = None) -> int:
    """Решение аналитика по фактам; возвращает число изменённых записей."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    new_status = REVIEW_ACTIONS.get(action)
    if not new_status:
        return 0
    return services.knowledge.review_facts(ids, new_status, USER, package)


# Кнопки «Пометить как противоречие» / «Пометить как дубликат» /
# «Отклонить пару» (рис. 2.14, секция пар-кандидатов).
def review_pair(pid: str, action: str,
                package: str | None = None, *,
                services: UiServices | None = None) -> bool:
    """Решение по паре-кандидату: противоречие / дубликат / отклонение пары."""
    services = services or get_services()
    package = resolve_package(package, services=services)
    return services.knowledge.review_pair(package, pid, action, USER)
