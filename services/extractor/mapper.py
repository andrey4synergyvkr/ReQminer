from __future__ import annotations

from collections import defaultdict

from contracts.facts import TYPE_TO_CLASS
from contracts.ontology import LifecycleStatus
from contracts.records import Fact
from contracts.workflow import EdgeType
from services.common.text_rules import common_tokens


def map(candidates: list[dict]) -> list[Fact]:
    """Приводит кандидатов к фактам; несмаппированные отбрасываются."""
    facts: list[Fact] = []
    for cand in candidates:
        if cand.get("type") not in TYPE_TO_CLASS:
            continue
        confidence = cand.get("confidence")
        fact: Fact = {
            "type": cand["type"],
            "title": cand["title"],
            # null из LLM - отсутствие оценки, а не «нулевая уверенность»
            "confidence": 0.5 if confidence is None else confidence,
            "status": LifecycleStatus.PENDING_REVIEW.value,
            "doc": cand.get("doc"),
            "frag": cand.get("frag"),
            "package": cand.get("package"),
        }
        for extra in ("definition", "raw_snippet"):
            if cand.get(extra):
                fact[extra] = cand[extra]
        facts.append(fact)
    return facts


def _best_epic(fact: dict, epics: list[dict]) -> dict | None:
    """Эпик документа с максимальным пересечением заголовка; при нулевом
    пересечении связывает только если эпик в документе один."""
    if not epics:
        return None
    best = max(epics, key=lambda e: common_tokens(e["title"], fact["title"]))
    if common_tokens(best["title"], fact["title"]) == 0 and len(epics) > 1:
        return None
    return best


def semantic_edges(facts: list[Fact]) -> list[dict]:
    """Семантические связи между фактами (после назначения id)."""
    edges: list[dict] = []
    terms = [f for f in facts if f["type"] == "term"]
    epics_by_doc: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        if f["type"] == "epic":
            epics_by_doc[f.get("doc")].append(f)
    for f in facts:
        if f["type"] in ("feature", "us"):
            epic = _best_epic(f, epics_by_doc.get(f.get("doc"), []))
            if epic is not None:
                edges.append({
                    "source": epic["id"], "target": f["id"],
                    "type": EdgeType.CONTAINS.value,
                })
        if f["type"] != "term":
            for term in terms:
                if term["title"].lower() in f["title"].lower():
                    edges.append({
                        "source": f["id"], "target": term["id"],
                        "type": EdgeType.USES_TERM.value,
                    })
    return edges
