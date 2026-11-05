from __future__ import annotations

from enum import StrEnum

from contracts.workflow import EdgeType


class NodeKind(StrEnum):
    """Типы узлов графа требований."""

    FACT = "fact"
    SOURCE = "source"


def project_graph(raw: dict) -> dict:
    """Дополняет сырые факты/рёбра Knowledge UI-узлами и трассировкой."""
    nodes: list[dict] = []
    edges: list[dict] = list(raw.get("edges", []))
    seen_src: dict[tuple[str, int], str] = {}
    for fact in raw.get("facts", []):
        nodes.append({
            "id": fact["id"],
            "kind": NodeKind.FACT.value,
            "type": fact.get("type"),
            "title": fact.get("title"),
            "doc": fact.get("doc"),
            "frag": fact.get("frag"),
        })
        doc, frag = fact.get("doc"), fact.get("frag")
        if doc is None or frag is None:
            continue
        key = (doc, frag)
        source = seen_src.get(key)
        if source is None:
            source = f"SRC-{doc.replace('.', '-')}-{frag}"
            seen_src[key] = source
            nodes.append({
                "id": source,
                "kind": NodeKind.SOURCE.value,
                "label": f"{doc}, фр. {frag}",
            })
        edges.append({
            "source": fact["id"],
            "target": source,
            "type": EdgeType.EXTRACTED_FROM.value,
        })
    return {"package": raw.get("package"), "nodes": nodes, "edges": edges}


def graph_stats(graph: dict) -> tuple[int, int]:
    """Счётчики узлов-фактов и рёбер для строки состояния."""
    facts = sum(
        1 for node in graph.get("nodes", [])
        if node.get("kind") == NodeKind.FACT
    )
    return facts, len(graph.get("edges", []))
