from __future__ import annotations

import time
from dataclasses import dataclass

from contracts.stores import ChunkStore, KnowledgeStore
from services.common import llm_cache
from services.common.llm_adapter import get_adapter
from services.common.logging import get_logger
from services.common.progress import ProgressTick
from services.extractor import mapper, pair_detector
from services.extractor.extractor import run as extract_candidates
from services.extractor.repository import knowledge_repo

log = get_logger("extractor.service")


@dataclass
class ExtractResult:
    """Метрики этапа извлечения фактов для формы прогресса прогона."""

    fragments: int = 0
    facts: int = 0
    pairs: int = 0
    llm_retries: int = 0


@dataclass
class PairResult:
    """Метрики этапа выявления противоречий."""

    pairs: int = 0
    llm_retries: int = 0


def extract_facts(package: str, *, knowledge: KnowledgeStore | None = None,
                  chunks: ChunkStore | None = None, adapter=None,
                  progress: ProgressTick | None = None) -> ExtractResult:
    """Извлекает факты из фрагментов пакета и пишет их в Knowledge."""
    store = knowledge or knowledge_repo
    llm = adapter or get_adapter()
    started = time.monotonic()
    cache_before = llm_cache.stats()["hits"]
    retries_before = llm.retries
    fragments, candidates = extract_candidates(
        package, chunks=chunks, adapter=llm, progress=progress
    )
    log.info(
        "Extractor %s: %d фрагментов прочитано, %d кандидатов",
        package, fragments, len(candidates),
    )
    store.add_facts(package, mapper.map(candidates))
    # связи строятся по сохраненным фактам - id уже назначены
    facts = store.list_facts(package)
    store.add_edges(package, mapper.semantic_edges(facts))
    result = ExtractResult(
        fragments=fragments,
        facts=store.facts_total(package),
        # повторы только этого прогона: счетчик адаптера общий на процесс
        llm_retries=max(0, llm.retries - retries_before),
    )
    log.info(
        "Extractor %s: фактов %d за %.1f с (повторов %d, из кэша %d)",
        package, result.facts, time.monotonic() - started,
        result.llm_retries, llm_cache.stats()["hits"] - cache_before,
    )
    return result


def detect_pairs(package: str, *, knowledge: KnowledgeStore | None = None,
                 adapter=None,
                 progress: ProgressTick | None = None) -> PairResult:
    """Выявляет пары-кандидаты по сохраненным фактам пакета."""
    store = knowledge or knowledge_repo
    llm = adapter or get_adapter()
    started = time.monotonic()
    cache_before = llm_cache.stats()["hits"]
    retries_before = llm.retries
    pairs = pair_detector.detect(
        store.list_facts(package), adapter=llm, progress=progress
    )
    store.add_pairs(package, pairs)
    result = PairResult(
        pairs=len(store.pairs_of(package)),
        llm_retries=max(0, llm.retries - retries_before),
    )
    log.info(
        "Extractor %s: пар %d за %.1f с (повторов %d, из кэша %d)",
        package, result.pairs, time.monotonic() - started,
        result.llm_retries, llm_cache.stats()["hits"] - cache_before,
    )
    return result


def extract(package: str, *, knowledge: KnowledgeStore | None = None,
            chunks: ChunkStore | None = None,
            adapter=None) -> ExtractResult:
    """Композиция этапов для сида и ленивой демо-сборки (без прогресса)."""
    llm = adapter or get_adapter()
    started = time.monotonic()
    cache_before = llm_cache.stats()["hits"]
    retries_before = llm.retries
    facts_result = extract_facts(
        package, knowledge=knowledge, chunks=chunks, adapter=llm
    )
    pairs_result = detect_pairs(package, knowledge=knowledge, adapter=llm)
    result = ExtractResult(
        fragments=facts_result.fragments,
        facts=facts_result.facts,
        pairs=pairs_result.pairs,
        llm_retries=max(0, llm.retries - retries_before),
    )
    log.info(
        "Extractor %s: итог %d фактов, %d пар за %.1f с "
        "(LLM %s, повторов %d, из кэша %d)",
        package, result.facts, result.pairs, time.monotonic() - started,
        llm.mode, result.llm_retries,
        llm_cache.stats()["hits"] - cache_before,
    )
    return result
