from __future__ import annotations

import json
from pathlib import Path

from demo.scenario import DEMO_PACKAGE, DEMO_QUARANTINE
from services.extractor import service as extractor_service
from services.extractor.repository import knowledge_repo
from services.ingestor.repository import chunks_repo
from services.orchestrator.metrics import collect

SNAPSHOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "control_example_snapshot.json"
)


def _current_snapshot() -> dict:
    chunks_repo.seed_demo(DEMO_PACKAGE)
    extractor_service.extract(DEMO_PACKAGE)

    facts = knowledge_repo.list_facts(DEMO_PACKAGE)
    pairs = knowledge_repo.pairs_of(DEMO_PACKAGE)
    stats = chunks_repo.stats(DEMO_PACKAGE)
    metrics = collect(
        DEMO_PACKAGE,
        {
            "documents": stats["documents"],
            "fragments": stats["fragments"],
            "quarantine": DEMO_QUARANTINE,
        },
        facts=facts,
        pairs=pairs,
    )
    return {
        "package": DEMO_PACKAGE,
        "metrics": metrics,
        "facts": [
            {
                "id": fact["id"],
                "type": fact["type"],
                "title": fact["title"],
                "status": fact["status"],
                "confidence": fact["confidence"],
                "doc": fact["doc"],
                "frag": fact["frag"],
            }
            for fact in facts
        ],
        "pairs": [
            {
                "id": pair["id"],
                "kind": pair["kind"],
                "a": pair["a"],
                "b": pair["b"],
                "status": pair["status"],
                "reason": pair["reason"],
            }
            for pair in pairs
        ],
    }


def test_control_example_matches_golden_master():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    actual = _current_snapshot()

    assert actual == expected, (
        "Поведение офлайн-конвейера изменилось. Если изменение намеренное — "
        f"обновите {SNAPSHOT.name} и объясните причину в коммите."
    )
