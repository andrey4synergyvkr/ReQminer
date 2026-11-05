from __future__ import annotations

from contracts.records import Fact

from .context import FactView


def fact_view(fact: Fact) -> FactView:
    """Представление одного факта для шаблона."""
    return FactView(
        id=fact.get("id", ""),
        type=fact.get("type", ""),
        title=fact.get("title", ""),
        confidence=fact.get("confidence", 0.0),
        status=fact.get("status", ""),
        doc=fact.get("doc"),
        frag=fact.get("frag"),
        definition=fact.get("definition", ""),
        acceptance=fact.get("acceptance", ""),
    )


def fact_views(facts: list[Fact]) -> tuple[FactView, ...]:
    """Представления списка фактов в исходном порядке."""
    return tuple(fact_view(fact) for fact in facts)
