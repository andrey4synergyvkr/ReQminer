from __future__ import annotations

import copy
import threading
from datetime import datetime

from contracts.ontology import LifecycleStatus
from contracts.pair_rules import detector_cascade, resolve_pair
from contracts.records import Fact, Graph, Pair, lifecycle_value, normalize_fact
from contracts.stores import KnowledgeStore
from contracts.workflow import PairStatus
from services.common.backends import KNOWLEDGE_NEO4J, lazy_backend


class InMemoryKnowledgeRepository:
    """In-memory хранилище графа фактов.

    Прогон идёт в фоновом потоке Orchestrator-а, а UI читает те же данные:
    методы защищены RLock, чтение списков отдает копию списка (объекты
    фактов остаются общими - на них опирается каскад статусов).
    """

    def __init__(self) -> None:
        self._facts: dict[str, list[dict]] = {}
        self._pairs: dict[str, list[dict]] = {}
        self._semantic_edges: dict[str, list[dict]] = {}
        self._lock = threading.RLock()

    def reset(self, package: str | None = None) -> None:
        """Очистка хранилища (изоляция приемочных тестов)."""
        with self._lock:
            if package is None:
                self._facts.clear()
                self._pairs.clear()
                self._semantic_edges.clear()
            else:
                self._facts.pop(package, None)
                self._pairs.pop(package, None)
                self._semantic_edges.pop(package, None)

    # --- запись (единственный писатель) --------------------------------------
    def add_facts(self, package: str, facts: list[Fact]) -> int:
        """Добавляет факты с назначением id; дубликаты (title+doc+frag)
        пропускаются. Возвращает число новых фактов."""
        with self._lock:
            bucket = self._facts.setdefault(package, [])
            known = {(f["title"], f["doc"], f["frag"]) for f in bucket}
            added = 0
            for fact in facts:
                normalize_fact(fact)
                key = (fact.get("title"), fact.get("doc"), fact.get("frag"))
                if key in known:
                    continue
                fact["id"] = f"F-{len(bucket) + 1:03d}"
                assert fact["id"].startswith("F-"), "id факта должен иметь префикс F-"
                # хранилище владеет своей записью: мутация входного dict
                # после add_facts() не должна менять сохранённый факт
                bucket.append(copy.deepcopy(fact))
                known.add(key)
                added += 1
            return added

    def add_pairs(self, package: str, pairs: list[Pair]) -> int:
        """Добавляет пары со статусом open и применяет каскад детектора.

        Противоречие переводит оба факта в needs_clarification, дубликат -
        менее уверенный в duplicate, более уверенный остаётся на проверке.
        Повторные пары пропускаются.
        """
        with self._lock:
            bucket = self._pairs.setdefault(package, [])
            known = {(p["a"], p["b"]) for p in bucket}
            added = 0
            for pair in pairs:
                key = (pair["a"], pair["b"])
                if key in known:
                    continue
                pair["id"] = f"P-{len(bucket) + 1}"
                assert pair["id"].startswith("P-"), "id пары должен иметь префикс P-"
                pair["status"] = PairStatus.OPEN.value
                stored = copy.deepcopy(pair)
                bucket.append(stored)
                known.add(key)
                self._apply_detector_cascade(package, stored)
                added += 1
            return added

    def _apply_detector_cascade(self, package: str, pair: Pair) -> None:
        """Статусы фактов по вердикту детектора (правило - в contracts)."""
        a = self._fact_ref(pair["a"], package)
        b = self._fact_ref(pair["b"], package)
        if a is None or b is None:
            return
        by_id = {a["id"]: a, b["id"]: b}
        for fid, status in detector_cascade(pair["kind"], a, b).items():
            fact = by_id.get(fid)
            if fact is not None:
                fact["status"] = status

    def add_edges(self, package: str, edges: list[dict]) -> int:
        """Добавляет семантические ребра; дубликаты пропускаются."""
        with self._lock:
            bucket = self._semantic_edges.setdefault(package, [])
            known = {(e["source"], e["target"], e["type"]) for e in bucket}
            added = 0
            for edge in edges:
                key = (edge["source"], edge["target"], edge["type"])
                if key in known:
                    continue
                bucket.append(copy.deepcopy(edge))
                known.add(key)
                added += 1
            return added

    # --- чтение --------------------------------------------------------------
    def list_facts(self, package: str) -> list[Fact]:
        """Снимок фактов: копии, а не живые записи хранилища."""
        with self._lock:
            return copy.deepcopy(self._facts.get(package, []))

    def get_fact(self, fid: str, package: str) -> Fact | None:
        """Факт по id в пакете (id уникальны только внутри пакета)."""
        with self._lock:
            fact = self._fact_ref(fid, package)
            return copy.deepcopy(fact) if fact is not None else None

    def _fact_ref(self, fid: str, package: str) -> Fact | None:
        """Внутренняя ссылка на факт: вызывать под `_lock`, наружу не отдавать."""
        for fact in self._facts.get(package, []):
            if fact["id"] == fid:
                return fact
        return None

    def pairs_of(self, package: str) -> list[Pair]:
        """Пары пакета."""
        with self._lock:
            return copy.deepcopy(self._pairs.get(package, []))

    def facts_total(self, package: str) -> int:
        """Число фактов пакета."""
        with self._lock:
            return len(self._facts.get(package, []))

    def count_by_status(self, package: str, status: LifecycleStatus | str) -> int:
        """Число фактов с указанным статусом."""
        value = lifecycle_value(status)
        with self._lock:
            return sum(1 for f in self._facts.get(package, []) if f["status"] == value)

    def pending_count(self, package: str) -> int:
        """Число фактов, ждущих проверки аналитиком."""
        return self.count_by_status(package, LifecycleStatus.PENDING_REVIEW)

    # --- решения аналитика (human-in-the-loop) -------------------------------
    def review_facts(self, ids: list[str], new_status: LifecycleStatus | str,
                     user: str, package: str) -> int:
        """Решение аналитика по фактам пакета; число изменённых записей.

        Id уникальны только внутри пакета, поэтому пакет обязателен:
        опечатка в нём не должна менять факты других пакетов.
        """
        status = lifecycle_value(new_status)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            changed = 0
            for f in self._facts.get(package, []):
                if f["id"] in ids:
                    f["status"] = status
                    f["reviewed_by"] = user
                    f["validated_at"] = now
                    changed += 1
            return changed

    def review_pair(self, package: str, pair_id: str, action: str, user: str) -> bool:
        """Решение по паре-кандидату; неизвестное действие отклоняется.

        Правило решения - contracts/pair_rules.resolve_pair: дубликат
        подтверждает более уверенный факт, противоречие отправляет оба на
        уточнение, отклонение пары возвращает оба в pending_review.
        """
        with self._lock:
            pair = next(
                (p for p in self._pairs.get(package, []) if p["id"] == pair_id), None
            )
            if pair is None:
                return False
            a = self._fact_ref(pair["a"], package)
            b = self._fact_ref(pair["b"], package)
            if a is None or b is None:
                return False
            resolution = resolve_pair(action, a, b)
            if resolution is None:
                return False
            pair["status"] = resolution.pair_status
            by_id = {a["id"]: a, b["id"]: b}
            for fid, status in resolution.statuses.items():
                fact = by_id[fid]
                fact["status"] = status
                if resolution.mark_reviewed:
                    fact["reviewed_by"] = user
            return True

    # --- граф требований (рис. 2.15) -----------------------------------------
    def get_graph(self, package: str) -> Graph:
        """Факты и семантические ребра без UI-проекции (её делает adapter)."""
        with self._lock:
            facts = copy.deepcopy(self._facts.get(package, []))
            semantic = copy.deepcopy(self._semantic_edges.get(package, []))
        return {"package": package, "facts": facts, "edges": semantic}


class _KnowledgeRepositoryFacade:
    """Ленивый выбор бэкенда: Neo4j при NEO4J_URI, иначе in-memory.

    Решение принимается один раз и липкое: отказ Neo4j не повторяется на
    каждом вызове, бэкенд не меняется посреди прогона (LazyBackend).
    """

    def __init__(self) -> None:
        self._fallback = InMemoryKnowledgeRepository()
        self._lazy = lazy_backend(KNOWLEDGE_NEO4J, lambda: self._fallback)

    def reset_backend(self) -> None:
        """Сброс выбора бэкенда (тесты: смена NEO4J_URI)."""
        self._fallback = InMemoryKnowledgeRepository()
        self._lazy.reset()

    def reset(self, package: str | None = None) -> None:
        """Очистка без разрешения бэкенда: тесты не платят пробу СУБД."""
        if self._lazy.resolved:
            self._lazy.backend().reset(package)
        else:
            self._fallback.reset(package)

    def backend_name(self) -> str:
        """Имя бэкенда для логов и диагностики UI."""
        return self._lazy.backend_name()

    def _resolve(self) -> KnowledgeStore:
        return self._lazy.backend()

    def __getattr__(self, name: str):
        return getattr(self._lazy.backend(), name)


# Единственный писатель в Knowledge: фасад над выбранным бэкендом.
knowledge_repo = _KnowledgeRepositoryFacade()
