from __future__ import annotations

from pytest_bdd import given, parsers, when

from services.builder import service as builder
from services.common.llm_adapter import get_adapter, reset_adapter


def make_fact(i: int, ftype: str, **extra) -> dict:
    fact = {
        "id": f"F-{i:03d}",
        "type": ftype,
        "title": f"Требование {i:03d} типа {ftype}",
        "confidence": 0.9,
        "status": "confirmed",
        "doc": "tz.md",
        "frag": i,
        "package": "2026-042",
    }
    fact.update(extra)
    return fact


@given(parsers.parse('пакет "{package}" обработан Extractor-ом и содержит факты в Knowledge'))
def package_processed(state, package):
    state["package"] = package.split()[-1]
    state["facts"] = []


@given('LlmAdapter отвечает заданным текстом разделов')
def llm_adapter_ready():
    reset_adapter()


@given('в Knowledge есть факты типов "epic", "feature", "us", "nfr", "constraint" и "term"')
def facts_of_types(state):
    types = ["epic", "feature", "us", "nfr", "constraint", "term"]
    state["facts"] = [make_fact(i, t) for i, t in enumerate(types, 1)]


@given(parsers.parse('в Knowledge нет фактов типа "{ftype}"'))
def no_term_facts(state, ftype):
    types = ["epic", "feature", "us", "nfr", "constraint", "vision"]
    state["facts"] = [make_fact(i, t) for i, t in enumerate(types, 1)]


@given('в Knowledge есть 47 фактов разных типов')
def facts_47(state):
    counts = {
        "epic": 2, "feature": 4, "us": 15, "nfr": 4,
        "constraint": 7, "term": 7, "vision": 8,
    }
    facts: list[dict] = []
    i = 1
    for ftype, count in counts.items():
        for _ in range(count):
            facts.append(make_fact(i, ftype))
            i += 1
    state["facts"] = facts


@given(parsers.parse('прогон пакета "{package}" завершен'))
def run_finished(state, package):
    state["package"] = package.split()[-1]
    state["facts"] = []


@given('метрики прогона переданы Builder-у')
def metrics_passed(state, demo_metrics):
    state["metrics"] = demo_metrics


@given(parsers.parse('пакет "{package}" обработан и каркас построен'))
def package_built(state, outbox_root, demo_metrics, package):
    state["package"] = package.split()[-1]
    state["facts"] = [make_fact(1, "epic"), make_fact(2, "us"), make_fact(3, "term")]
    state["docs"] = builder.build(state["package"], state["facts"], demo_metrics)


@when('Builder строит каркас пакета')
def build_skeleton(state, outbox_root, demo_metrics):
    metrics = state.get("metrics", demo_metrics)
    state["docs"] = builder.build(state["package"], state["facts"], metrics)


@when('Builder строит каркас пакета дважды')
def build_skeleton_twice(state, outbox_root, demo_metrics):
    metrics = state.get("metrics", demo_metrics)
    state["first_docs"] = builder.build(state["package"], state["facts"], metrics)
    state["docs"] = builder.build(state["package"], state["facts"], metrics)
