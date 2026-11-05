from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

from contracts.ontology import DocumentChunk
from services.common.llm_adapter import get_adapter
from services.extractor.repository import knowledge_repo
from services.extractor.service import ExtractResult, PairResult, extract
from services.orchestrator import runner

PACKAGE = "2026-860"


class FakeKnowledge:

    def __init__(self) -> None:
        self.facts: list[dict] = []
        self.pairs: list[dict] = []
        self.edges: list[dict] = []

    def add_facts(self, package: str, facts: list[dict]) -> int:
        self.facts.extend(facts)
        return len(facts)

    def list_facts(self, package: str) -> list[dict]:
        return [dict(fact) for fact in self.facts]

    def add_edges(self, package: str, edges: list[dict]) -> int:
        self.edges.extend(edges)
        return len(edges)

    def add_pairs(self, package: str, pairs: list[dict]) -> int:
        self.pairs.extend(pairs)
        return len(pairs)

    def facts_total(self, package: str) -> int:
        return len(self.facts)

    def pairs_of(self, package: str) -> list[dict]:
        return list(self.pairs)


class FakeChunks:

    def list_chunks(self, package: str) -> list[DocumentChunk]:
        text = "Как аналитик, я хочу загружать входящие документы."
        return [DocumentChunk(
            id=f"{package}:doc.md:1",
            chunk_index=1,
            content=text,
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            metadata=json.dumps({"doc": "doc.md"}),
        )]

    def stats(self, package: str) -> dict:
        return {"documents": 0, "fragments": 0}

    def seed_demo(self, package: str = "") -> None:
        pass


class FakeRegistry:

    def __init__(self, inbox) -> None:
        self.inbox = inbox
        self.packages = {
            "2026-861": {
                "id": "2026-861", "name": "Пакет", "status": "run",
                "files": [], "documents": 0,
            },
        }
        self.runs: dict[str, dict] = {}

    def get_package(self, pid: str):
        package = self.packages.get(pid)
        return copy.deepcopy(package) if package else None

    def get_run(self, pid: str):
        run = self.runs.get(pid)
        return copy.deepcopy(run) if run else None

    def set_run(self, pid: str, run: dict) -> None:
        self.runs[pid] = copy.deepcopy(run)

    def update_package(self, pid: str, **fields) -> None:
        self.packages[pid].update(copy.deepcopy(fields))

    def inbox_dir(self, package: str):
        return self.inbox


def test_extractor_uses_injected_stores():
    knowledge = FakeKnowledge()
    chunks = FakeChunks()

    result = extract(
        PACKAGE, knowledge=knowledge, chunks=chunks, adapter=get_adapter()
    )

    assert result.facts == 1
    assert len(knowledge.facts) == 1
    assert knowledge_repo.facts_total(PACKAGE) == 0


def test_runner_uses_injected_services(tmp_path):
    knowledge = FakeKnowledge()
    chunks = FakeChunks()
    registry = FakeRegistry(tmp_path)
    calls: dict[str, object] = {}

    def fake_extract_facts(pid, *, knowledge, chunks, progress=None):
        calls["extract"] = (pid, knowledge, chunks)
        return ExtractResult(fragments=0, facts=0, llm_retries=0)

    def fake_detect_pairs(pid, *, knowledge, progress=None):
        calls["pairs"] = (pid, knowledge)
        return PairResult()

    def fake_build(pid, facts, metrics, **kwargs):
        calls["build"] = (pid, facts, metrics)
        return {}

    extractor = SimpleNamespace(
        extract_facts=fake_extract_facts, detect_pairs=fake_detect_pairs
    )
    run = runner.run_package(
        "2026-861",
        chunks=chunks,
        knowledge=knowledge,
        registry_service=registry,
        extractor_service=extractor,
        builder_service=fake_build,
    )

    assert run["state"] == "done"
    assert registry.runs["2026-861"]["state"] == "done"
    assert registry.packages["2026-861"]["status"] == "done"
    assert calls["extract"][1] is knowledge
    assert calls["extract"][2] is chunks
    assert calls["pairs"][1] is knowledge
    assert calls["build"][0] == "2026-861"
