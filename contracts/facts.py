from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FactTypeSpec:
    """Тип факта: ключ, класс онтологии (None для vision) и участие в парах."""

    key: str
    ontology: str | None
    pairable: bool = True


FACT_TYPE_SPECS = (
    FactTypeSpec("epic", "Epic"),
    FactTypeSpec("feature", "Feature"),
    FactTypeSpec("us", "UserStory"),
    FactTypeSpec("nfr", "QualityGoal"),
    FactTypeSpec("constraint", "BusinessConstraint"),
    FactTypeSpec("term", "GlossaryTerm", pairable=False),
    FactTypeSpec("vision", None),
)

FACT_TYPE_KEYS = frozenset(spec.key for spec in FACT_TYPE_SPECS)
PAIRABLE_TYPES = frozenset(spec.key for spec in FACT_TYPE_SPECS if spec.pairable)
TYPE_TO_CLASS = {spec.key: spec.ontology for spec in FACT_TYPE_SPECS}
FACT_TYPE_ORDER = {spec.key: index for index, spec in enumerate(FACT_TYPE_SPECS)}
