from __future__ import annotations

from contracts import workflow
from contracts.stores import (
    ChunkStore,
    RunStore,
    SeedableChunkStore,
    SeedableRunStore,
)
from services.ingestor.repository import InMemoryChunkRepository
from services.orchestrator import registry as registry_module
from services.orchestrator.registry import InMemoryRegistry
from services.web_ui.data import adapter, graph


def test_status_labels_are_presentation_only():
    assert not hasattr(registry_module, "PACKAGE_STATUS_LABELS")
    assert adapter.PACKAGE_STATUS_LABELS["done"] == "каркас сформирован"
    assert adapter.PACKAGE_STATUS_LABELS["failed"] == "прогон упал"


def test_node_kind_is_ui_concept():
    assert not hasattr(workflow, "NodeKind")
    assert graph.NodeKind.FACT.value == "fact"
    assert graph.NodeKind.SOURCE.value == "source"


def test_seed_methods_are_demo_ports():
    assert "seed_demo" not in ChunkStore.__dict__
    assert "seed_demo" in SeedableChunkStore.__dict__
    assert "load_seeds" not in RunStore.__dict__
    assert "load_seeds" in SeedableRunStore.__dict__


def test_backends_satisfy_production_and_demo_protocols():
    chunks = InMemoryChunkRepository()
    assert isinstance(chunks, ChunkStore)
    assert isinstance(chunks, SeedableChunkStore)
    registry = InMemoryRegistry()
    assert isinstance(registry, RunStore)
    assert isinstance(registry, SeedableRunStore)
