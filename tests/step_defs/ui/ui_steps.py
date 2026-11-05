from __future__ import annotations

import re
import time
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from pytest_bdd import given, parsers, when

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTROL_TZ = REPO_ROOT / "demo" / "calculator-tz.md"

PACKAGE_NAME = "ТЗ Калькулятор"
CONTROL_DOC = "calculator-tz.md"

_RUN_TIMEOUT = 30.0
_POLL_PAUSE = 0.05


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OUTBOX_ROOT", str(tmp_path / "outbox"))

    from services.orchestrator import registry, scheduler

    registry.reset_backend()
    registry.configure(tmp_path / "inbox", force=True)
    with scheduler._lock:
        scheduler._active.clear()

    from fastapi.testclient import TestClient

    from services.web_ui import app as ui_app
    import importlib

    adapter_startup = importlib.import_module(
        "services.web_ui.data.adapter.startup"
    )
    adapter_startup._demo_built.clear()
    with TestClient(ui_app.app) as client:
        env = SimpleNamespace(client=client, page=None, package=None, panel=None)
        yield env

    with scheduler._lock:
        scheduler._active.clear()
    registry.reset_backend()


_TAG_RE = re.compile(r"<[^>]+>")
_ROW_RE = re.compile(r'<tr data-pkg="(?P<id>[^"]+)">(?P<body>.*?)</tr>', re.S)
_PAIR_ROW_RE = re.compile(
    r'name="pair_id" value="(?P<id>[^"]+)"[^>]*>\s*</td>\s*'
    r'<td class="pair">(?P<a>.*?)</td>\s*'
    r'<td class="pair">(?P<b>.*?)</td>\s*'
    r'<td class="reason">(?P<reason>.*?)</td>',
    re.S,
)
_PENDING_ROW_RE = re.compile(
    r'name="fact_id" value="(?P<id>F-\d+)"[^>]*>\s*</td>\s*'
    r'<td><span class="tag [^"]+">[^<]*</span></td>\s*<td>(?P<title>.*?)</td>',
    re.S,
)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", fragment))).strip()


def _rows(html: str) -> list[dict]:
    rows = []
    for match in _ROW_RE.finditer(html):
        body = match.group("body")
        name = re.search(r'<td class="pkg">(.*?)</td>', body, re.S)
        documents = re.search(r'<td class="num">(\d+)</td>', body)
        badge = re.search(r'<span class="badge [^"]+">(.*?)</span>', body, re.S)
        rows.append({
            "id": match.group("id"),
            "name": _text(name.group(1)) if name else "",
            "documents": int(documents.group(1)) if documents else None,
            "status": _text(badge.group(1)) if badge else "",
        })
    return rows


def _row(html: str, name: str) -> dict:
    for row in _rows(html):
        if row["name"] == name:
            return row
    raise AssertionError(f"в реестре нет пакета «{name}»: {_rows(html)}")


def _run_state(html: str) -> str:
    match = re.search(r'<p class="run-state">(.*?)</p>', html, re.S)
    assert match, "на экране нет строки состояния прогона"
    return _text(match.group(1))


def _review_state(html: str) -> tuple[int, int]:
    match = re.search(r"спорные факты \((\d+)\) и пары-кандидаты \((\d+)\)", html)
    assert match, f"на экране нет счетчиков сверки:\n{_text(html)[:400]}"
    return int(match.group(1)), int(match.group(2))


def _facts_total(html: str) -> tuple[int, int]:
    match = re.search(r"Всего фактов: (\d+), показано: (\d+)", html)
    assert match, "на экране нет итоговой строки списка фактов"
    return int(match.group(1)), int(match.group(2))


def _pending_badge(html: str) -> int:
    match = re.search(r"К подтверждению \((\d+)\)", html)
    assert match, "на экране нет кнопки «К подтверждению»"
    return int(match.group(1))


def _pair_rows(html: str) -> list[dict]:
    return [
        {
            "id": m.group("id"),
            "text": _text(m.group("a") + " " + m.group("b")),
            "reason": _text(m.group("reason")),
        }
        for m in _PAIR_ROW_RE.finditer(html)
    ]


def _pending_rows(html: str) -> list[dict]:
    return [
        {"id": m.group("id"), "title": _text(m.group("title"))}
        for m in _PENDING_ROW_RE.finditer(html)
    ]


def _metrics(html: str) -> list[tuple[str, str]]:
    return [
        (label.strip(), value.strip())
        for value, label in re.findall(
            r'<div class="v">([^<]*)</div><div class="k">([^<]*)</div>', html
        )
    ]


def _metric(html: str, label: str) -> str:
    values = [value for key, value in _metrics(html) if key == label]
    assert values, f"нет метрики «{label}»: {_metrics(html)}"
    return values[0]


def _sections(html: str) -> dict[str, int]:
    return {
        _text(title): int(count)
        for title, count in re.findall(
            r"<td>(.*?)</td>\s*<td class=\"file\">[^<]*</td>\s*<td class=\"num\">(\d+)</td>",
            html,
            re.S,
        )
    }


def _gaps(html: str) -> str:
    match = re.search(r'<div class="gaps">(.*?)</div>', html, re.S)
    assert match, "на экране отчета нет блока пробелов модели"
    return _text(match.group(1))


def _open(ui, url: str, **params):
    ui.page = ui.client.get(url, params=params or None)
    assert ui.page.status_code == 200, f"GET {url}: {ui.page.status_code}"
    return ui.page


def _submit(ui, path: str, fields: dict):
    pairs: list[tuple[str, str]] = []
    for key, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            pairs.append((key, str(item)))
    ui.page = ui.client.post(
        path,
        content=urlencode(pairs).encode("utf-8"),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    return ui.page


def _upload(ui, name: str, documents: dict[str, bytes],
            doc_type: str = "техническое задание"):
    data = {"name": name, "direction": "обращение заказчика"}
    files = []
    for index, (filename, content) in enumerate(documents.items()):
        data[f"filetype-{index}"] = doc_type
        files.append(("files", (filename, content, "text/markdown")))
    ui.page = ui.client.post("/packages", data=data, files=files)
    return ui.page


def _wait_run(ui, pid: str) -> str:
    deadline = time.monotonic() + _RUN_TIMEOUT
    while True:
        panel = ui.client.get(f"/packages/{pid}/run/panel")
        assert panel.status_code == 200, f"панель прогона: {panel.status_code}"
        if "Автообновление" not in panel.text:
            return panel.text
        assert time.monotonic() < deadline, (
            f"прогон {pid} не завершился за {_RUN_TIMEOUT} с"
        )
        time.sleep(_POLL_PAUSE)


def _wait_rerun(pid: str, previous: dict) -> None:
    from services.orchestrator import registry, scheduler

    deadline = time.monotonic() + _RUN_TIMEOUT
    while time.monotonic() < deadline:
        run = registry.get_run(pid) or {}
        changed = (run.get("state") != previous.get("state")
                   or run.get("started") != previous.get("started"))
        if changed and run.get("state") != "run" and not scheduler.active(pid):
            return
        time.sleep(_POLL_PAUSE)
    raise AssertionError(f"повторный прогон {pid} не завершился за {_RUN_TIMEOUT} с")


@given("аналитик открыл реестр пакетов")
def registry_opened(ui):
    page = _open(ui, "/packages")
    assert "Реестр пакетов" in page.text


@when(parsers.parse('аналитик загружает пакет «{name}» с документом «{filename}»'))
def upload_package(ui, name, filename):
    if filename == CONTROL_DOC:
        content = CONTROL_TZ.read_bytes()
    else:
        content = "%PDF-1.4\nскан без текстового слоя".encode("utf-8")
    _upload(ui, name, {filename: content})
    ui.package = _row(ui.page.text, name)["id"]


@given('пакет «ТЗ Калькулятор» загружен и прогнан')
def control_package_uploaded(ui):
    _upload(ui, PACKAGE_NAME, {CONTROL_DOC: CONTROL_TZ.read_bytes()})
    ui.package = _row(ui.page.text, PACKAGE_NAME)["id"]
    _wait_run(ui, ui.package)


@when("аналитик открывает экран прогона и дожидается завершения")
def open_run_and_wait(ui):
    _open(ui, f"/packages/{ui.package}/run")
    ui.panel = _wait_run(ui, ui.package)


@when("аналитик открывает список фактов пакета")
def open_facts(ui):
    _open(ui, "/facts", package=ui.package)


@when("аналитик открывает экран подтверждения пакета")
def open_review(ui):
    _open(ui, "/review", package=ui.package)


@when(parsers.parse('аналитик помечает пару про «{marker}» дубликатом'))
def mark_duplicate(ui, marker):
    page = _open(ui, "/review", package=ui.package)
    pair = next((p for p in _pair_rows(page.text) if marker in p["text"]), None)
    assert pair, f"нет пары с формулировкой «{marker}»"
    response = _submit(ui, "/review/pairs", {
        "package": ui.package,
        "action": "pair_duplicate",
        "pair_id": pair["id"],
    })
    assert response.status_code == 303, response.status_code
    assert f"package={ui.package}" in response.headers["location"]


@when(parsers.parse('аналитик помечает пару про «{marker}» противоречием'))
def mark_contradiction(ui, marker):
    page = _open(ui, "/review", package=ui.package)
    pair = next((p for p in _pair_rows(page.text) if marker in p["text"]), None)
    assert pair, f"нет пары с формулировкой «{marker}»"
    response = _submit(ui, "/review/pairs", {
        "package": ui.package,
        "action": "pair_contradiction",
        "pair_id": pair["id"],
    })
    assert response.status_code == 303, response.status_code
    assert f"package={ui.package}" in response.headers["location"]


@when("аналитик подтверждает все оставшиеся факты, кроме пары противоречия")
def confirm_remaining_facts(ui):
    _open(ui, "/review", package=ui.package)
    ids = [
        row["id"] for row in _pending_rows(ui.page.text)
        if "Время отклика" not in row["title"]
    ]
    assert ids, "на экране нет фактов для подтверждения"
    response = _submit(ui, "/review/facts", {
        "package": ui.package,
        "action": "confirm",
        "fact_id": ids,
    })
    assert response.status_code == 303, response.status_code
    assert f"package={ui.package}" in response.headers["location"]


@when("аналитик повторно запускает анализ пакета")
def rerun_analysis(ui):
    from services.orchestrator import registry

    previous = registry.get_run(ui.package) or {}
    response = ui.client.post(
        f"/packages/{ui.package}/analyze", follow_redirects=False
    )
    assert response.status_code == 303, response.status_code
    _wait_rerun(ui.package, previous)


@when("аналитик открывает граф требований")
def open_graph(ui):
    _open(ui, "/graph", package=ui.package)


@when("аналитик открывает экран результатов")
def open_report(ui):
    _open(ui, "/report", package=ui.package)


@when(parsers.parse('аналитик просматривает раздел "{path}"'))
def preview_section(ui, path):
    _open(ui, "/report/preview", package=ui.package, path=path)


@when("аналитик выгружает каркас в markdown")
def export_skeleton(ui):
    ui.page = ui.client.get("/report/export/md", params={"package": ui.package})
    assert ui.page.status_code == 200
    assert ui.page.headers["content-type"] == "application/zip"


@when("аналитик скачивает аналитический отчет")
def download_report(ui):
    ui.page = ui.client.get("/report/download", params={"package": ui.package})
    assert ui.page.status_code == 200
    assert ui.page.headers["content-type"].startswith("text/markdown")


@when("аналитик отправляет форму приема без файлов")
def submit_empty_form(ui):
    ui.page = ui.client.post(
        "/packages",
        data={"name": "Пустая форма", "direction": "обращение заказчика"},
    )
