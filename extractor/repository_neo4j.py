from __future__ import annotations

from datetime import datetime

from contracts.ontology import LifecycleStatus
from contracts.pair_rules import detector_cascade, resolve_pair
from contracts.records import Fact, Graph, Pair, lifecycle_value, normalize_fact
from contracts.workflow import PairStatus

from services.common.logging import get_logger

log = get_logger("extractor.repository_neo4j")

# свойства узла Fact, перечисленные явно: у dict-факта может быть что
# угодно (acceptance из тестов), неизвестное складывается в props
_FACT_FIELDS = (
    "type", "title", "confidence", "status", "doc", "frag",
    "raw_snippet", "definition", "reviewed_by", "validated_at",
)


def _fact_props(fact: dict) -> dict:
    """Свойства узла Fact из dict-факта (id/package идут отдельно)."""
    props = {k: fact.get(k) for k in _FACT_FIELDS if fact.get(k) is not None}
    # остальные поля (acceptance и т.п.) сохраняются как есть
    for key, value in fact.items():
        if key not in _FACT_FIELDS and key not in ("id", "package"):
            props[key] = value
    return props


def _fact_from_record(node, package: str) -> dict:
    """dict-факт из узла Neo4j (обратная проекция)."""
    fact = dict(node)
    fact.pop("uid", None)
    fact["package"] = package
    return fact


def _src_uid(doc: str, frag: int) -> str:
    slug = doc.replace(".", "-")
    return f"SRC-{slug}-{frag}"


class Neo4jKnowledgeRepository:
    """Хранилище Knowledge на Neo4j: те же методы, что у in-memory.

    Факт хранится узлом Fact с uid пакет:id, источник - узлом Source,
    связанным ребром EXTRACTED_FROM. Семантические связи и пары - рёбра
    RELATES и PAIR. MERGE по uid делает повторную запись идемпотентной,
    а каскад статусов применяется в add_pairs той же транзакцией.
    """

    def _session(self):
        # driver гарантированно не None: бэкенд создается только при успехе
        # подключения (graph_db.init_graph в repository.py)
        from services.common.graph_db import get_driver

        return get_driver().session()

    def reset(self, package: str | None = None) -> None:
        """Очистка (тесты); без аргумента - весь граф."""
        with self._session() as session:
            if package is None:
                session.run("MATCH (n) DETACH DELETE n")
            else:
                session.run(
                    "MATCH (n) WHERE n.package = $package OR "
                    "n.uid STARTS WITH $prefix DETACH DELETE n",
                    package=package, prefix=f"{package}:",
                )

    # --- запись (единственный писатель) --------------------------------------
    def add_facts(self, package: str, facts: list[Fact]) -> int:
        """Добавляет факты с назначением id; дубликаты (title+doc+frag)
        пропускаются. Источник и ребро «извлечен из» создаются вместе
        с фактом - одной транзакцией. Возвращает число новых фактов.

        Пачка пишется батчем: два чтения (известные факты и максимальный id)
        и три UNWIND-запроса на всю пачку вместо запросов на каждый факт.
        """
        if not facts:
            return 0
        with self._session() as session:
            # дедуп: известные сочетания содержимого и источника - одним чтением
            known = {
                (row["title"], row["doc"], row["frag"])
                for row in session.run(
                    "MATCH (f:Fact {package: $package}) "
                    "RETURN f.title AS title, f.doc AS doc, f.frag AS frag",
                    package=package,
                )
            }
            # следующий id: max(суффикс) по пакету - детерминированно
            # и переживает рестарт (в in-memory - len(bucket)+1)
            row = session.run(
                "MATCH (f:Fact {package: $package}) "
                "RETURN max(toInteger(split(f.id, '-')[1])) AS n",
                package=package,
            ).single()
            num = (row["n"] or 0) if row else 0

            rows: list[dict] = []
            for fact in facts:
                normalize_fact(fact)
                key = (fact.get("title"), fact.get("doc"), fact.get("frag"))
                if key in known:
                    continue
                num += 1
                fid = f"F-{num:03d}"
                assert fid.startswith("F-"), "id факта должен иметь префикс F-"
                fact["id"] = fid  # мутация входа - контракт in-memory версии
                fact["package"] = package
                rows.append({
                    "uid": f"{package}:{fid}",
                    "fid": fid,
                    "props": _fact_props(fact),
                })
                known.add(key)
            if not rows:
                return 0
            session.execute_write(lambda tx: self._write_facts(tx, package, rows))
        return len(rows)

    @staticmethod
    def _write_facts(tx, package: str, rows: list[dict]) -> None:
        """Запись пачки фактов; источники и ребра «извлечен из» - тоже пачкой."""
        tx.run(
            "UNWIND $rows AS row "
            "MERGE (f:Fact {uid: row.uid}) "
            "SET f += row.props, f.id = row.fid, f.package = $package",
            rows=rows, package=package,
        )
        sources: dict[str, str] = {}
        for row in rows:
            doc, frag = row["props"].get("doc"), row["props"].get("frag")
            if doc is not None and frag is not None:
                sources[_src_uid(doc, frag)] = f"{doc}, фр. {frag}"
        if not sources:
            return
        tx.run(
            "UNWIND $rows AS row "
            "MERGE (s:Source {uid: row.src}) "
            "SET s.label = row.label, s.package = $package",
            rows=[{"src": src, "label": label} for src, label in sources.items()],
            package=package,
        )
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (f:Fact {uid: row.uid}), (s:Source {uid: row.src}) "
            "MERGE (f)-[r:EXTRACTED_FROM]->(s) SET r.type = $rtype",
            rows=[
                {"uid": row["uid"],
                 "src": _src_uid(row["props"]["doc"], row["props"]["frag"])}
                for row in rows
                if row["props"].get("doc") is not None
                and row["props"].get("frag") is not None
            ],
            rtype="извлечен из",
        )

    def add_pairs(self, package: str, pairs: list[Pair]) -> int:
        """Добавляет пары-кандидаты со статусом open и применяет каскад
        статусов детектора: противоречие - оба факта needs_clarification,
        дубликат - менее уверенный duplicate. Дубликаты пары id
        пропускаются. Пара и каскад фиксируются одной транзакцией;
        пачка пишется батчем UNWIND.
        """
        if not pairs:
            return 0
        with self._session() as session:
            known = {
                (row["a"], row["b"])
                for row in session.run(
                    "MATCH (a:Fact {package: $package})-[p:PAIR]->(b:Fact) "
                    "RETURN a.id AS a, b.id AS b",
                    package=package,
                )
            }
            row = session.run(
                "MATCH (:Fact {package: $package})-[p:PAIR]->() "
                "RETURN max(toInteger(split(p.id, '-')[1])) AS n",
                package=package,
            ).single()
            num = (row["n"] or 0) if row else 0

            rows: list[dict] = []
            for pair in pairs:
                key = (pair["a"], pair["b"])
                if key in known:
                    continue
                num += 1
                pair["id"] = f"P-{num}"
                assert pair["id"].startswith("P-"), "id пары должен иметь префикс P-"
                pair["status"] = PairStatus.OPEN.value
                rows.append(pair)
                known.add(key)
            if not rows:
                return 0
            # каскад считается по текущим статусам фактов: терминальные
            # решения аналитика повторный прогон не понижает
            ids = {pair["a"] for pair in rows} | {pair["b"] for pair in rows}
            facts: dict[str, Fact] = {}
            for record in session.run(
                "MATCH (f:Fact {package: $package}) WHERE f.id IN $ids RETURN f",
                package=package, ids=sorted(ids),
            ):
                fact = _fact_from_record(record["f"], package)
                facts[fact["id"]] = fact
            changes: dict[str, str] = {}
            for pair in rows:
                a, b = facts.get(pair["a"]), facts.get(pair["b"])
                if a is not None and b is not None:
                    changes.update(detector_cascade(pair["kind"], a, b))
            session.execute_write(
                lambda tx: self._write_pairs(tx, package, rows, changes)
            )
        return len(rows)

    @staticmethod
    def _write_pairs(tx, package: str, pairs: list[dict],
                     changes: dict[str, str]) -> None:
        """Запись пачки пар и каскада статусов (правило - в contracts)."""
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (a:Fact {uid: row.a}), (b:Fact {uid: row.b}) "
            "MERGE (a)-[p:PAIR]->(b) "
            "SET p.id = row.id, p.kind = row.kind, p.reason = row.reason, "
            "    p.status = row.status, p.package = $package",
            rows=[
                {"a": f"{package}:{pair['a']}", "b": f"{package}:{pair['b']}",
                 "id": pair["id"], "kind": pair["kind"],
                 "reason": pair.get("reason"), "status": PairStatus.OPEN.value}
                for pair in pairs
            ],
            package=package,
        )
        if changes:
            tx.run(
                "UNWIND $rows AS row "
                "MATCH (f:Fact {uid: row.uid}) SET f.status = row.status",
                rows=[
                    {"uid": f"{package}:{fid}", "status": status}
                    for fid, status in changes.items()
                ],
            )

    def add_edges(self, package: str, edges: list[dict]) -> int:
        """Добавляет семантические ребра; дубликаты пропускаются.

        Ребра пишутся одним UNWIND-запросом: MERGE по типу связи идемпотентен,
        отдельная проверка существования на каждое ребро не нужна.
        """
        if not edges:
            return 0
        with self._session() as session:
            known = {
                (row["s"], row["d"], row["t"])
                for row in session.run(
                    "MATCH (a:Fact {package: $package})-[r:RELATES]->(b:Fact) "
                    "RETURN a.id AS s, b.id AS d, r.type AS t",
                    package=package,
                )
            }
            rows = []
            for edge in edges:
                key = (edge["source"], edge["target"], edge["type"])
                if key in known:
                    continue
                rows.append({"a": f"{package}:{edge['source']}",
                             "b": f"{package}:{edge['target']}",
                             "t": edge["type"]})
                known.add(key)
            if not rows:
                return 0
            session.run(
                "UNWIND $rows AS row "
                "MATCH (a:Fact {uid: row.a}), (b:Fact {uid: row.b}) "
                "MERGE (a)-[r:RELATES {type: row.t}]->(b) "
                "SET r.package = $package",
                rows=rows, package=package,
            )
        return len(rows)

    # --- чтение ----------------------------------------------------------------
    def list_facts(self, package: str) -> list[dict]:
        """Порядок - по возрастанию числового суффикса id (как insertion
        order in-memory версии)."""
        with self._session() as session:
            nodes = session.run(
                "MATCH (f:Fact {package: $package}) "
                "RETURN f ORDER BY toInteger(split(f.id, '-')[1])",
                package=package,
            ).data()
        return [_fact_from_record(row["f"], package) for row in nodes]

    def get_fact(self, fid: str, package: str) -> Fact | None:
        """Факт по id в пакете (id уникальны только внутри пакета)."""
        with self._session() as session:
            row = session.run(
                "MATCH (f:Fact {package: $package, id: $fid}) RETURN f LIMIT 1",
                package=package, fid=fid,
            ).single()
        return _fact_from_record(row["f"], package) if row else None

    def pairs_of(self, package: str) -> list[Pair]:
        """Пары пакета."""
        with self._session() as session:
            rows = session.run(
                "MATCH (a:Fact {package: $package})-[p:PAIR]->(b:Fact) "
                "RETURN a.id AS a, b.id AS b, p.id AS id, p.kind AS kind, "
                "       p.reason AS reason, p.status AS status "
                "ORDER BY toInteger(split(p.id, '-')[1])",
                package=package,
            ).data()
        return [
            {"a": r["a"], "b": r["b"], "id": r["id"], "kind": r["kind"],
             "reason": r["reason"], "status": r["status"]}
            for r in rows
        ]

    def facts_total(self, package: str) -> int:
        """Число фактов пакета - агрегат в СУБД, без выгрузки узлов."""
        with self._session() as session:
            row = session.run(
                "MATCH (f:Fact {package: $package}) RETURN count(f) AS c",
                package=package,
            ).single()
        return row["c"]

    def count_by_status(self, package: str, status: LifecycleStatus | str) -> int:
        """Число фактов с указанным статусом."""
        value = lifecycle_value(status)
        with self._session() as session:
            row = session.run(
                "MATCH (f:Fact {package: $package, status: $status}) "
                "RETURN count(f) AS c",
                package=package, status=value,
            ).single()
        return row["c"]

    def pending_count(self, package: str) -> int:
        """Число фактов, ждущих проверки аналитиком."""
        return self.count_by_status(package, LifecycleStatus.PENDING_REVIEW)

    # --- решения аналитика (human-in-the-loop) ---------------------------------
    def review_facts(self, ids: list[str], new_status: LifecycleStatus | str,
                     user: str, package: str) -> int:
        """Решение аналитика по фактам пакета; число изменённых записей.

        Пакет обязателен: id уникальны только внутри пакета, и глобальный
        поиск при опечатке менял бы чужие факты.
        """
        status = lifecycle_value(new_status)
        now = datetime.now().isoformat(timespec="seconds")
        with self._session() as session:
            summary = session.run(
                "MATCH (f:Fact {package: $package}) "
                "WHERE f.id IN $ids "
                "SET f.status = $status, f.reviewed_by = $user, "
                "    f.validated_at = $now RETURN count(f) AS c",
                package=package, ids=ids, status=status,
                user=user, now=now,
            ).single()
        return summary["c"]

    def review_pair(self, package: str, pair_id: str, action: str, user: str) -> bool:
        """Решение по паре; поиск и запись - одна транзакция.

        Правило решения - contracts/pair_rules.resolve_pair: дубликат
        подтверждает более уверенный факт, противоречие отправляет оба на
        уточнение, отклонение возвращает оба в pending_review.
        """
        with self._session() as session:
            return session.execute_write(
                lambda tx: self._review_pair_tx(
                    tx, package, pair_id, action, user
                )
            )

    @staticmethod
    def _review_pair_tx(tx, package: str, pair_id: str, action: str,
                        user: str) -> bool:
        record = tx.run(
            "MATCH (a:Fact {package: $package})-[p:PAIR {id: $pid}]->(b:Fact) "
            "RETURN a.id AS a_id, b.id AS b_id, "
            "       a.status AS a_status, b.status AS b_status, "
            "       a.confidence AS a_conf, b.confidence AS b_conf",
            package=package, pid=pair_id,
        ).single()
        if record is None:
            return False
        a = {"id": record["a_id"], "status": record["a_status"],
             "confidence": record["a_conf"]}
        b = {"id": record["b_id"], "status": record["b_status"],
             "confidence": record["b_conf"]}
        resolution = resolve_pair(action, a, b)
        if resolution is None:
            return False
        tx.run(
            "MATCH (a:Fact {package: $package})-[p:PAIR {id: $pid}]->(:Fact) "
            "SET p.status = $status",
            package=package, pid=pair_id, status=resolution.pair_status,
        )
        if resolution.statuses:
            rows = [
                {"uid": f"{package}:{fid}", "status": status}
                for fid, status in resolution.statuses.items()
            ]
            tx.run(
                "UNWIND $rows AS row "
                "MATCH (f:Fact {uid: row.uid}) SET f.status = row.status",
                rows=rows,
            )
            if resolution.mark_reviewed:
                tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (f:Fact {uid: row.uid}) SET f.reviewed_by = $user",
                    rows=rows, user=user,
                )
        return True

    # --- граф требований (рис. 2.15) -------------------------------------------
    def get_graph(self, package: str) -> Graph:
        """Факты и семантические ребра без UI-проекции (её делает adapter)."""
        facts = self.list_facts(package)
        with self._session() as session:
            rows = session.run(
                "MATCH (a:Fact {package: $package})-[r:RELATES]->(b:Fact) "
                "RETURN a.id AS source, b.id AS target, r.type AS type",
                package=package,
            ).data()
        edges = [
            {"source": r["source"], "target": r["target"], "type": r["type"]}
            for r in rows
        ]
        return {"package": package, "facts": facts, "edges": edges}
