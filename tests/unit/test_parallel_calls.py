from __future__ import annotations

import hashlib
import json
import threading
import time

import pytest

from contracts.ontology import DocumentChunk, ParsingStatus, SourceArtifact
from services.common import llm_adapter, parallel, settings
from services.extractor import extractor
from services.ingestor.repository import chunks_repo


class Stub:

    def __init__(self, mode: str) -> None:
        self.mode = mode


def test_cloud_mode_runs_calls_concurrently():
    started = time.monotonic()
    result = parallel.map_calls(
        Stub("cloud"), lambda i: (time.sleep(0.1), i * 2)[1], [1, 2, 3, 4]
    )
    elapsed = time.monotonic() - started
    assert result == [2, 4, 6, 8]
    assert elapsed < 0.3, f"вызовы шли последовательно ({elapsed:.2f} с)"


def test_order_is_preserved_even_when_calls_finish_out_of_order():
    def call(i: int) -> int:
        time.sleep(0.03 * (5 - i))
        return i

    assert parallel.map_calls(Stub("cloud"), call, [1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]


def test_on_done_fires_once_per_item_in_both_modes():
    for mode in ("cloud", "offline"):
        seen: list[int] = []
        lock = threading.Lock()

        def on_done(item: int) -> None:
            with lock:
                seen.append(item)

        result = parallel.map_calls(
            Stub(mode), lambda i: i * 2, [1, 2, 3, 4], on_done=on_done
        )
        assert result == [2, 4, 6, 8]
        assert sorted(seen) == [1, 2, 3, 4], mode


def test_on_done_fires_even_when_call_fails():
    seen: list[int] = []

    def call(i: int) -> int:
        if i == 2:
            raise ValueError("сбой")
        return i

    with pytest.raises(ValueError):
        parallel.map_calls(Stub("offline"), call, [1, 2, 3], on_done=seen.append)
    assert seen == [1, 2]


def test_offline_mode_is_sequential():
    active: list[int] = []
    peak: list[int] = []
    lock = threading.Lock()

    def call(i: int) -> int:
        with lock:
            active.append(i)
            peak.append(len(active))
        time.sleep(0.01)
        with lock:
            active.remove(i)
        return i

    parallel.map_calls(Stub("offline"), call, [1, 2, 3, 4])
    assert max(peak) == 1, "offline-режим не должен использовать потоки"


def test_concurrency_setting(monkeypatch):
    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    assert parallel.worker_count(Stub("cloud")) == 8
    monkeypatch.setenv("LLM_CONCURRENCY", "0")
    assert parallel.worker_count(Stub("cloud")) == 0
    monkeypatch.setenv("LLM_CONCURRENCY", "abc")
    assert parallel.worker_count(Stub("cloud")) == settings.llm_concurrency()
    monkeypatch.setenv("LLM_CONCURRENCY", "8")
    assert parallel.worker_count(Stub("offline")) == 0


def test_zero_concurrency_runs_in_caller_thread(monkeypatch):
    monkeypatch.setenv("LLM_CONCURRENCY", "0")
    threads = set()

    def call(i: int) -> int:
        threads.add(threading.get_ident())
        return i

    parallel.map_calls(Stub("cloud"), call, [1, 2, 3])
    assert threads == {threading.get_ident()}


def test_exception_propagates():
    def call(i: int) -> int:
        if i == 2:
            raise ValueError("сбой модели")
        return i

    with pytest.raises(ValueError):
        parallel.map_calls(Stub("cloud"), call, [1, 2, 3])


def test_retry_counter_is_thread_safe():
    adapter = llm_adapter._BaseAdapter(mode="cloud")
    threads = [threading.Thread(target=adapter._count_retry) for _ in range(200)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert adapter.retries == 200


PACKAGE = "2026-778"
DOCS = {"a.md": ["первый", "второй", "третий"], "b.md": ["четвертый", "пятый"]}


def _seed_chunks() -> None:
    chunks_repo.reset(PACKAGE)
    for doc, texts in DOCS.items():
        chunks = [
            DocumentChunk(
                id=f"{PACKAGE}:{doc}:{i}", chunk_index=i, content=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                start_offset=0, end_offset=len(text), token_count=1,
                metadata=json.dumps({"doc": doc}),
            )
            for i, text in enumerate(texts, 1)
        ]
        chunks_repo.save(
            PACKAGE,
            SourceArtifact(id=f"{PACKAGE}:{doc}", file_path=doc, file_name=doc,
                           total_chunks=len(chunks), parsing_status=ParsingStatus.PARSED),
            chunks,
        )


def test_extraction_keeps_fragment_order_in_cloud_mode(monkeypatch):

    class FakeCloud(Stub):
        def __init__(self) -> None:
            super().__init__("cloud")

        def extract_candidates(self, text: str) -> list[dict]:
            time.sleep(0.01)
            return [{"type": "us", "title": f"История {text}", "confidence": 0.9}]

    monkeypatch.setattr(llm_adapter, "_adapter", FakeCloud())
    _seed_chunks()

    count, candidates = extractor.run(PACKAGE)

    assert count == 5
    assert [c["doc"] for c in candidates] == ["a.md"] * 3 + ["b.md"] * 2
    assert [c["frag"] for c in candidates] == [1, 2, 3, 1, 2]
    assert [c["title"] for c in candidates] == [
        f"История {text}" for texts in DOCS.values() for text in texts
    ]
