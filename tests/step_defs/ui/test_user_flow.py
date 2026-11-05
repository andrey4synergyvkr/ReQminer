from __future__ import annotations

import io
import re
import zipfile

from pytest_bdd import parsers, scenarios, then
from ui_steps import *  # noqa: F401,F403
from ui_steps import (
    PACKAGE_NAME,
    _facts_total,
    _gaps,
    _metric,
    _open,
    _pair_rows,
    _pending_badge,
    _review_state,
    _row,
    _run_state,
    _sections,
)

scenarios("../../features/ui/user_flow.feature")


def _status_count(ui, status: str) -> int:
    page = _open(ui, "/facts", package=ui.package, status=status)
    return _facts_total(page.text)[1]


@then(parsers.parse('в реестре есть пакет «{name}» с одним документом в работе'))
def package_in_registry(ui, name):
    row = _row(ui.page.text, name)
    assert row["documents"] == 1, row
    assert row["status"].split(" · ")[0] in ("обработка", "подтверждение фактов"), row


@then(parsers.parse('пакет ждет подтверждения фактов ({count:d})'))
def package_awaits_confirmation(ui, count):
    page = _open(ui, f"/packages/{ui.package}/run")
    assert f"ожидают подтверждения факты ({count})" in _run_state(page.text)


@then("все четыре этапа конвейера завершены")
def all_stages_done(ui):
    assert ui.panel.count('class="badge done"') == 4, ui.panel


@then(parsers.parse('панель показывает прогресс {percent:d} процентов'))
def panel_shows_progress(ui, percent):
    match = re.search(
        r'role="progressbar".*?aria-valuenow="(\d+)"', ui.panel, re.S
    )
    assert match, f"на панели нет progressbar:\n{ui.panel[:600]}"
    assert int(match.group(1)) == percent
    assert "aria-valuetext=" in ui.panel, "у progressbar нет доступного описания"
    assert 'class="progress-card done"' in ui.panel


@then(parsers.parse('прогон обработал {fragments:d} фрагментов и извлек {facts:d} фактов'))
def run_metrics(ui, fragments, facts):
    assert _metric(ui.panel, "фрагментов") == str(fragments)
    assert _metric(ui.panel, "фактов") == str(facts)


@then(parsers.parse('список содержит {total:d} фактов, из них {pending:d} ожидают подтверждения'))
def facts_list(ui, total, pending):
    page = _open(ui, "/facts", package=ui.package)
    assert _facts_total(page.text) == (total, total)
    assert _pending_badge(page.text) == pending


@then(parsers.parse('фильтр по статусу "{status}" показывает {count:d} фактов'))
def facts_filter_status(ui, status, count):
    assert _status_count(ui, status) == count


@then(parsers.parse('поиск по тексту «{query}» показывает {count:d} факта'))
def facts_search(ui, query, count):
    page = _open(ui, "/facts", package=ui.package, q=query)
    assert _facts_total(page.text)[1] == count


@then(parsers.parse('фильтр достоверности "{threshold}" показывает {count:d} факта'))
def facts_filter_confidence(ui, threshold, count):
    page = _open(ui, "/facts", package=ui.package, min_conf=threshold)
    assert _facts_total(page.text)[1] == count


@then(parsers.parse('на экране {pending:d} спорных фактов и {pairs:d} пары-кандидата'))
def review_screen(ui, pending, pairs):
    assert _review_state(ui.page.text) == (pending, pairs)


@then(parsers.parse('среди пар есть дубликат формулировок про «{duplicate}» '
                    'и противоречие про «{contradiction}»'))
def review_pair_kinds(ui, duplicate, contradiction):
    pairs = _pair_rows(ui.page.text)
    dup = next((p for p in pairs if duplicate in p["text"]), None)
    con = next((p for p in pairs if contradiction in p["text"]), None)
    assert dup, f"нет пары про «{duplicate}»: {pairs}"
    assert con, f"нет пары про «{contradiction}»: {pairs}"
    assert "совпадающий смысл" in dup["reason"], dup
    assert "разные значения одного параметра" in con["reason"], con


@then(parsers.parse('открытых пар не остается, а решения требуют {count:d} фактов'))
def pairs_resolved(ui, count):
    page = _open(ui, "/review", package=ui.package)
    pending, pairs = _review_state(page.text)
    assert pairs == 0
    assert pending == count


@then("фильтр «ожидает подтверждения» не находит фактов")
def no_pending_facts(ui):
    page = _open(ui, "/facts", package=ui.package, status="pending_review")
    assert _facts_total(page.text)[1] == 0
    assert "Факты не найдены" in page.text


@then(parsers.parse('в пакете {confirmed:d} подтвержденных фактов, '
                    '{duplicate:d} дубликат и {clarify:d} факта на уточнении'))
def status_distribution(ui, confirmed, duplicate, clarify):
    assert _status_count(ui, "confirmed") == confirmed
    assert _status_count(ui, "duplicate") == duplicate
    assert _status_count(ui, "needs_clarification") == clarify


@then(parsers.parse('повторный прогон не создает дублей: {facts:d} фактов '
                    'и решения аналитика сохранены'))
def rerun_idempotent(ui, facts):
    page = _open(ui, "/facts", package=ui.package)
    assert _facts_total(page.text) == (facts, facts)
    assert _status_count(ui, "confirmed") == 7
    assert _status_count(ui, "duplicate") == 1
    assert _status_count(ui, "needs_clarification") == 2


@then(parsers.parse('пакет в реестре переходит в статус «{status}»'))
def registry_status(ui, status):
    page = _open(ui, "/packages")
    assert _row(page.text, PACKAGE_NAME)["status"] == status

@then(parsers.parse('граф содержит {facts:d} узлов-фактов и {edges:d} связей'))
def graph_contents(ui, facts, edges):
    assert f"({facts} узлов, {edges} связей)" in _run_state(ui.page.text)
    data = ui.client.get("/graph/data", params={"package": ui.package}).json()
    assert sum(1 for n in data["nodes"] if n["kind"] == "fact") == facts
    assert len(data["edges"]) == edges


@then(parsers.parse('отчет показывает {facts:d} фактов, {pending:d} ожидают '
                    'подтверждения и пару каждого вида'))
def report_metrics(ui, facts, pending):
    html = ui.page.text
    assert _metric(html, "фактов") == str(facts)
    assert _metric(html, "ожидает подтверждения") == str(pending)
    assert _metric(html, "пара противоречий") == "1"
    assert _metric(html, "пара дубликатов") == "1"


@then(parsers.parse('в каркасе пять разделов: {functional:d} фактов в функциональных '
                    'требованиях и {nonfunctional:d} в нефункциональных'))
def skeleton_sections(ui, functional, nonfunctional):
    sections = _sections(ui.page.text)
    assert len(sections) == 5, sections
    assert sections["Функциональные требования"] == functional
    assert sections["Нефункциональные требования"] == nonfunctional
    assert sections["Ограничения"] == 1, sections


@then(parsers.parse('пробелы модели указывают на {count:d} пользовательские '
                    'истории без критериев приемки'))
def model_gaps(ui, count):
    match = re.search(r"не заданы критерии приемки для (\d+) из (\d+)", _gaps(ui.page.text))
    assert match, _gaps(ui.page.text)
    assert int(match.group(1)) == count


@then("предпросмотр содержит формулировку про журнал вычислений")
def preview_contains_story(ui):
    assert "журнал вычислений" in ui.page.text
    assert "<li>" in ui.page.text, "markdown каркаса не отрендерен"


@then(parsers.parse('архив содержит {count:d} файлов каркаса и аналитический отчет пакета'))
def archive_contents(ui, count):
    archive = zipfile.ZipFile(io.BytesIO(ui.page.content))
    names = archive.namelist()
    assert len(names) == count, names
    assert "analysis_report.md" in names, names
    report = archive.read("analysis_report.md").decode("utf-8")
    assert f"пакет {ui.package}" in report


@then(parsers.parse('файл отчета содержит метрику «фактов» со значением {value:d}'))
def report_download_contains_metric(ui, value):
    assert f"| фактов | {value} |" in ui.page.text


@then(parsers.parse('в реестре пакет «{name}» отклонен с причиной «{reason}»'))
def package_rejected(ui, name, reason):
    row = _row(ui.page.text, name)
    assert row["status"] == f"отклонен: {reason}", row
    assert row["documents"] == 0, row


@then("экран прогона сообщает об отклонении")
def run_rejected(ui):
    page = _open(ui, f"/packages/{ui.package}/run")
    assert "прогон отклонен" in _run_state(page.text)


@then("экран результатов показывает, что каркас не сформирован")
def report_empty(ui):
    page = _open(ui, "/report", package=ui.package)
    assert "каркас ещё не сформирован" in page.text


@then(parsers.parse('приложение не падает, а пакет отклонен с причиной «{reason}»'))
def empty_form_rejected(ui, reason):
    assert ui.page.status_code == 200, ui.page.status_code
    row = _row(ui.page.text, "Пустая форма")
    assert row["status"] == f"отклонен: {reason}", row
