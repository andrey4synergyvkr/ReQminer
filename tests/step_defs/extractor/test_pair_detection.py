from __future__ import annotations

from extractor_steps import *  # noqa: F401,F403
from extractor_steps import PACKAGE, reset_package_fragments
from pytest_bdd import given, parsers, scenarios, then

from services.common.llm_adapter import get_adapter
from services.extractor.repository import knowledge_repo

scenarios("../../features/extractor/pair_detection.feature")

_DUPLICATE_FRAGMENTS = [
    "Функциональность «Экспорт отчета в XLSX»: выгрузка данных заказчику.",
    "Как аналитик, я хочу экспортировать отчет в XLSX для заказчика.",
]

_PREFILTER_FRAGMENTS = [
    "Как аналитик, я хочу сортировать записи реестра.",
    "Как оператор, я хочу печатать ярлыки для коробок.",
    "Время архивации данных не должно превышать восьми часов.",
    "Функциональность «Импорт прайс-листов»: загрузка файлов поставщиков.",
    "Эпик — крупная функциональная цель, объединяющая несколько функций системы.",
    "Бюджет проекта не должен превышать 2 млн рублей.",
    "Стратегическая цель — единая точка приёма требований от всех заказчиков.",
    "Как руководитель, я хочу подписывать акты сверок.",
    "Как аналитик, я хочу экспортировать отчет в XLSX.",
    "Как аналитик, я хочу экспортировать результаты в XLSX.",
]


@given('два факта указывают разные сроки внедрения')
def contradictory_deadlines():
    reset_package_fragments([
        "Срок внедрения системы — не позднее трёх месяцев с даты подписания договора.",
        "Со стороны заказчика реалистичный срок внедрения — шесть месяцев, с учётом согласований.",
    ])


@given('два факта описывают одно требование с разной уверенностью')
def duplicate_requirement():
    reset_package_fragments(_DUPLICATE_FRAGMENTS)


@given('пакет содержит 10 фактов, из них похожи только 2')
def ten_facts_two_similar():
    reset_package_fragments(_PREFILTER_FRAGMENTS)


def _pair_of_kind(kind: str) -> dict:
    pairs = [p for p in knowledge_repo.pairs_of(PACKAGE) if p["kind"] == kind]
    assert pairs, f"пара типа {kind} не создана"
    return pairs[0]


def _pair_facts(pair: dict) -> tuple[dict, dict]:
    return (
        knowledge_repo.get_fact(pair["a"], PACKAGE),
        knowledge_repo.get_fact(pair["b"], PACKAGE),
    )


@then(parsers.parse('создана пара-кандидат типа "{kind}" с причиной'))
def pair_with_reason(kind):
    pair = _pair_of_kind(kind)
    assert pair["reason"], pair["id"]


@then('обоим фактам пары присвоен статус "needs_clarification"')
def pair_facts_need_clarification():
    pair = _pair_of_kind("contradiction")
    a, b = _pair_facts(pair)
    assert a["status"] == b["status"] == "needs_clarification"


@then(parsers.parse('создана пара-кандидат типа "{kind}"'))
def pair_created(kind):
    _pair_of_kind(kind)


@then('менее уверенный факт получил статус "duplicate"')
def less_confident_is_duplicate():
    pair = _pair_of_kind("duplicate")
    a, b = _pair_facts(pair)
    dup = a if (a.get("confidence") or 0) < (b.get("confidence") or 0) else b
    assert dup["status"] == "duplicate", dup["id"]


@then('более уверенный факт остался в статусе "pending_review"')
def more_confident_is_pending():
    pair = _pair_of_kind("duplicate")
    a, b = _pair_facts(pair)
    keep = a if (a.get("confidence") or 0) >= (b.get("confidence") or 0) else b
    assert keep["status"] == "pending_review", keep["id"]


@then('LlmAdapter получил на проверку только похожую пару фактов')
def only_similar_pair_judged():
    verdicts = get_adapter().verdicts
    assert len(verdicts) == 1, verdicts
    assert verdicts[0]["verdict"] is not None
