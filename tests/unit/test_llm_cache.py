from __future__ import annotations

import json

import pytest

from services.common import llm_adapter, llm_cache
from services.common.llm_adapter import CloudLlmAdapter

CANDIDATES = json.dumps(
    {"candidates": [{"type": "us", "title": "История", "confidence": 0.9}]},
    ensure_ascii=False,
)


class CountingAdapter(CloudLlmAdapter):

    def __init__(self, answer: str = CANDIDATES) -> None:
        llm_adapter._BaseAdapter.__init__(self, mode="cloud")
        self._model = "test-model"
        self._answer = answer
        self.asks = 0

    def _ask(self, system: str, user: str) -> str:
        self.asks += 1
        return self._answer


def test_key_depends_on_model_and_both_prompts():
    base = llm_cache.key("m1", "system", "user")
    assert base == llm_cache.key("m1", "system", "user")
    assert base != llm_cache.key("m2", "system", "user")
    assert base != llm_cache.key("m1", "system2", "user")
    assert base != llm_cache.key("m1", "system", "user2")
    assert llm_cache.key("m", "ab", "c") != llm_cache.key("m", "a", "bc")


def test_set_get_roundtrip_and_stats():
    key = llm_cache.key("m", "s", "u")
    assert llm_cache.get(key) is None
    llm_cache.set(key, "ответ")
    assert llm_cache.get(key) == "ответ"
    stats = llm_cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1


def test_reset_clears_memory():
    llm_cache.set(llm_cache.key("m", "s", "u"), "ответ")
    llm_cache.reset()
    assert llm_cache.get(llm_cache.key("m", "s", "u")) is None
    assert llm_cache.stats()["hits"] == 0


def test_memory_is_limited(monkeypatch):
    monkeypatch.setattr(llm_cache, "MAX_ENTRIES", 2)
    for i in range(3):
        llm_cache.set(llm_cache.key("m", f"prompt {i}", "u"), f"ответ {i}")
    assert llm_cache.stats()["entries"] == 2
    assert llm_cache.get(llm_cache.key("m", "prompt 0", "u")) is None
    assert llm_cache.get(llm_cache.key("m", "prompt 2", "u")) == "ответ 2"


def test_cache_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "0")
    assert not llm_cache.enabled()
    monkeypatch.setenv("LLM_CACHE", "1")
    assert llm_cache.enabled()


def test_repeated_extraction_uses_cache():
    adapter = CountingAdapter()
    first = adapter.extract_candidates("Фрагмент документа с требованием.")
    second = adapter.extract_candidates("Фрагмент документа с требованием.")
    assert first == second
    assert adapter.asks == 1, "повторный фрагмент не должен идти в модель"
    assert llm_cache.stats()["hits"] == 1


def test_different_fragment_is_not_cached():
    adapter = CountingAdapter()
    adapter.extract_candidates("Первый фрагмент.")
    adapter.extract_candidates("Второй фрагмент.")
    assert adapter.asks == 2


def test_repeated_completion_uses_cache():
    adapter = CountingAdapter(answer="# Ограничения\n\nтекст")
    first = adapter.complete("system", "user")
    second = adapter.complete("system", "user")
    assert first == second
    assert adapter.asks == 1


def test_disabled_cache_calls_model_every_time(monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "0")
    adapter = CountingAdapter()
    adapter.extract_candidates("Фрагмент.")
    adapter.extract_candidates("Фрагмент.")
    assert adapter.asks == 2


def test_failed_call_is_not_cached(monkeypatch):
    monkeypatch.setattr(llm_adapter, "_RETRY_PAUSE", 0)
    adapter = CountingAdapter(answer="")
    assert adapter._ask_with_retries("s", "u") is None
    assert adapter.asks == llm_adapter._RETRIES
    assert llm_cache.get(llm_cache.key("test-model", "s", "u")) is None


@pytest.fixture
def sqlite_pg(monkeypatch):
    from sqlalchemy import create_engine
    from services.common import llm_cache_pg

    engine = create_engine("sqlite://")
    llm_cache_pg.reset_backend()
    monkeypatch.setattr(llm_cache_pg, "_engine", lambda: engine)
    yield llm_cache_pg
    llm_cache_pg.reset_backend()


def test_pg_layer_roundtrip(sqlite_pg):
    sqlite_pg.put("key-1", "ответ модели", model="test-model")
    assert sqlite_pg.get("key-1") == "ответ модели"
    sqlite_pg.put("key-1", "новый ответ", model="test-model")
    assert sqlite_pg.get("key-1") == "новый ответ"
    sqlite_pg.clear()
    assert sqlite_pg.get("key-1") is None


def test_l2_hit_is_promoted_to_l1(sqlite_pg):
    key = llm_cache.key("test-model", "s", "u")
    sqlite_pg.put(key, "ответ из прошлого запуска")
    assert llm_cache.get(key) == "ответ из прошлого запуска"
    assert llm_cache.stats()["entries"] == 1
    sqlite_pg.clear()
    assert llm_cache.get(key) == "ответ из прошлого запуска"
