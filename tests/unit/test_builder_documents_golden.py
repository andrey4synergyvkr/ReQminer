from __future__ import annotations

import json
import re
from pathlib import Path

from services.builder import service as builder

PACKAGE = "2026-903"
SNAPSHOT = Path(__file__).resolve().parents[1] / "data" / "builder_documents_snapshot.json"

METRICS = {
    "documents": 3, "fragments": 12, "facts": 7, "confirmed": 5,
    "pending": 2, "pairs_contradiction": 1, "pairs_duplicate": 1,
    "quarantine": 0, "llm_retries": 0,
}

_TIMESTAMP = re.compile(
    r"_Сформирован \d{2}\.\d{2}\.\d{4} \d{2}:\d{2}_"
)


def fact(i: int, ftype: str, title: str, **extra) -> dict:
    item = {
        "id": f"F-{i:03d}", "type": ftype, "title": title,
        "confidence": 0.9, "status": "confirmed", "doc": "tz.md",
        "frag": i, "package": PACKAGE,
    }
    item.update(extra)
    return item


FULL = [
    fact(1, "vision", "Видение продукта"),
    fact(2, "term", "Обращение", definition="Запрос заказчика на доработку."),
    fact(3, "epic", "Обработка обращений"),
    fact(4, "feature", "Регистрация обращения"),
    fact(5, "us", "Как аналитик, я хочу видеть список обращений"),
    fact(6, "nfr", "Время отклика не более 2 секунд"),
    fact(7, "constraint", "Бюджет проекта не более 2 млн"),
    fact(8, "us", "Отклоненная история", status="rejected"),
    fact(9, "feature", "Дубликат фичи", status="duplicate"),
]
EMPTY = [fact(1, "vision", "Видение продукта")]


def _normalize(docs: dict[str, str]) -> dict[str, str]:
    return {
        name: _TIMESTAMP.sub("_Сформирован <timestamp>_", text)
        for name, text in docs.items()
    }


def _expected() -> dict[str, dict[str, str]]:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_full_fact_set_matches_golden(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTBOX_ROOT", str(tmp_path / "outbox"))

    docs = builder.build(PACKAGE, FULL, METRICS)

    assert _normalize(docs) == _expected()["full"]


def test_empty_sections_match_golden(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTBOX_ROOT", str(tmp_path / "outbox"))

    docs = builder.build(PACKAGE, EMPTY, METRICS)

    assert _normalize(docs) == _expected()["empty"]
    assert "раздел пуст: термины не извлечены" in docs["glossary.md"]
