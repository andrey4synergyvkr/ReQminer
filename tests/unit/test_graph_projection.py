from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.extractor.repository import InMemoryKnowledgeRepository
from services.web_ui.data import adapter
from services.web_ui.data.adapter import graph as adapter_graph

PACKAGE = "2026-820"


@pytest.fixture
def projected(monkeypatch):
    repo = InMemoryKnowledgeRepository()
    facts = [
        {"type": "epic", "title": "Эпик", "confidence": 0.9,
         "status": "confirmed", "doc": "tz.md", "frag": 1},
        {"type": "us", "title": "История", "confidence": 0.8,
         "status": "confirmed", "doc": "tz.md", "frag": 1},
    ]
    repo.add_facts(PACKAGE, facts)
    repo.add_edges(PACKAGE, [{
        "source": facts[0]["id"], "target": facts[1]["id"],
        "type": "содержит",
    }])

    monkeypatch.setattr(
        adapter_graph, "resolve_package",
        lambda package=None, **kwargs: PACKAGE,
    )
    services = SimpleNamespace(knowledge=repo)
    return adapter.get_graph(PACKAGE, services=services)


def test_projection_adds_fact_and_source_nodes(projected):
    kinds = [node["kind"] for node in projected["nodes"]]
    assert kinds.count("fact") == 2
    assert kinds.count("source") == 1
    source = next(n for n in projected["nodes"] if n["kind"] == "source")
    assert source["id"] == "SRC-tz-md-1"
    assert "tz.md" in source["label"]


def test_projection_keeps_semantic_and_trace_edges(projected):
    types = {edge["type"] for edge in projected["edges"]}
    assert "содержит" in types
    assert "извлечен из" in types
    trace = [e for e in projected["edges"] if e["type"] == "извлечен из"]
    assert all(e["target"].startswith("SRC-") for e in trace)


def test_raw_graph_has_no_presentation(monkeypatch):
    repo = InMemoryKnowledgeRepository()
    repo.add_facts(PACKAGE, [{
        "type": "us", "title": "История", "confidence": 0.8,
        "status": "confirmed", "doc": "tz.md", "frag": 1,
    }])
    raw = repo.get_graph(PACKAGE)

    assert raw["facts"] and raw["edges"] == []
    assert "nodes" not in raw
