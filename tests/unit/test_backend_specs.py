from __future__ import annotations

from services.common.backends import (
    CHUNKS_SQL,
    KNOWLEDGE_NEO4J,
    REGISTRY_SQL,
    BackendSpec,
    lazy_backend,
)


def test_spec_open_passes_arguments():
    spec = BackendSpec("sum", lambda a, b: a + b)
    assert spec.name == "sum"
    assert spec.open(2, 3) == 5


def test_named_specs_are_registered():
    assert {CHUNKS_SQL.name, KNOWLEDGE_NEO4J.name, REGISTRY_SQL.name} == {
        "chunks-sql", "knowledge-neo4j", "registry-sql",
    }


def test_lazy_backend_uses_spec_once():
    calls: list[int] = []
    spec = BackendSpec("counter", lambda: calls.append(1) or object())
    fallback = object()

    lazy = lazy_backend(spec, lambda: fallback)

    assert lazy.backend() is lazy.backend()
    assert len(calls) == 1


def test_lazy_backend_falls_back_when_probe_rejects():
    fallback = object()
    lazy = lazy_backend(BackendSpec("none", lambda: None), lambda: fallback)
    assert lazy.backend() is fallback
