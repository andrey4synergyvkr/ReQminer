from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import traceback
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import httpx
except ImportError as exc:
    raise SystemExit(
        "Нужен extra [test]: pip install -e \".[test,db,graph]\""
    ) from exc

DEFAULT_DOCUMENT = REPO_ROOT / "demo" / "калькулятор.md"
DEFAULT_PACKAGE_NAME = "Приёмка Калькулятор"
DIRECTION = "обращение заказчика"
DOC_TYPE = "техническое задание"
POLL_SECONDS = 2
DEFAULT_TIMEOUT = 900
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

EXPECTED_ZIP_NAMES = (
    "vision_and_strategy.md",
    "glossary.md",
    "functional_reqs/epics.md",
    "functional_reqs/features.md",
    "functional_reqs/user_stories.md",
    "non_functional_reqs/quality_goals.md",
    "constraints.md",
    "analysis_report.md",
)
SECTION_FILES = EXPECTED_ZIP_NAMES[:-1]
EXCLUDED_STATUSES = {"rejected", "duplicate"}

_PG_TABLES = (
    "registry_packages",
    "registry_runs",
    "document_chunks",
    "source_artifacts",
    "llm_cache",
)

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


class AcceptanceError(RuntimeError):
    """Критическая ошибка прогона: протокол фиксирует FAIL и причину."""


@dataclass
class Check:
    """Одна проверка приёмки."""
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Acceptance:
    """Контекст приёмочного прогона."""
    args: argparse.Namespace
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    document: Path | None = None
    document_sha256: str = ""
    document_size: int = 0
    commit: str = ""
    command: str = ""
    model: str = ""
    llm_mode: str = ""
    protocol_path: Path | None = None
    engine: Any = None
    driver: Any = None
    before_clean: dict = field(default_factory=dict)
    after_clean: dict = field(default_factory=dict)
    clean_output: str = ""
    server: Any = None
    http: Any = None
    backend_line: str = ""
    llm_line: str = ""
    empty_checks: dict = field(default_factory=dict)
    pid: str | None = None
    package: dict = field(default_factory=dict)
    run: dict = field(default_factory=dict)
    first_run: dict = field(default_factory=dict)
    first_duration: float = 0.0
    facts: list[dict] = field(default_factory=list)
    pairs: list[dict] = field(default_factory=list)
    chunks: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    first_pending: int = 0
    first_open_pairs: int = 0
    panel_html: str = ""
    facts_html: str = ""
    review_html: str = ""
    review_state: tuple[int, int] | None = None
    pair_actions: list[dict] = field(default_factory=list)
    review_before: dict = field(default_factory=dict)
    review_after: dict = field(default_factory=dict)
    second_run: dict = field(default_factory=dict)
    second_duration: float = 0.0
    report_html: str = ""
    report_sections: dict = field(default_factory=dict)
    report_metrics: dict = field(default_factory=dict)
    report_gaps: str = ""
    report_prompt: str = ""
    zip_names: list[str] = field(default_factory=list)
    zip_sha256: str = ""
    report_md: str = ""
    graph_data: dict = field(default_factory=dict)
    graph_html: str = ""
    persistence_before: dict = field(default_factory=dict)
    persistence_after: dict = field(default_factory=dict)
    negative: list[dict] = field(default_factory=list)
    error: str = ""

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        """Добавляет проверку в список."""
        self.checks.append(Check(name, bool(ok), detail))
        print(
            f"[{'PASS' if ok else 'FAIL'}] {name}"
            + (f" — {detail}" if detail else ""),
            flush=True,
        )
        if not ok:
            raise AcceptanceError(f"{name}: {detail}" if detail else name)

    def note(self, text: str) -> None:
        """Добавляет пояснение в протокол."""
        self.notes.append(text)
        print(f"[NOTE] {text}", flush=True)


# --- общие утилиты -----------------------------------------------------------

def fail(message: str) -> None:
    """Прерывает прогон с сообщением об ошибке."""
    raise AcceptanceError(message)


def run_cmd(
    cmd: list[str],
    *,
    check: bool = True,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Запускает команду и возвращает результат."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if check and result.returncode != 0:
        fail(
            f"команда {' '.join(cmd)} вернула {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_commit() -> str:
    """Короткий хеш текущего коммита и пустая строка, если git недоступен."""
    try:
        return run_cmd(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    except Exception:
        return "unknown"


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", fragment))).strip()


def _cell(value: Any, limit: int = 160) -> str:
    text = "—" if value is None else str(value)
    text = text.replace("|", "\\|").replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Собирает markdown-таблицу из заголовков и строк."""
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return "\n".join(lines)


# --- разбор HTML и markdown --------------------------------------------------

def html_metrics(html: str) -> dict[str, str]:
    """Метрики из HTML панели отчёта."""
    return {
        label.strip(): value.strip()
        for value, label in re.findall(
            r'<div class="v">([^<]*)</div><div class="k">([^<]*)</div>', html
        )
    }


def html_sections(html: str) -> dict[str, int]:
    """Число фактов по разделам из HTML."""
    return {
        _text(title): int(count)
        for title, count in re.findall(
            r"<td>(.*?)</td>\s*<td class=\"file\">[^<]*</td>\s*"
            r"<td class=\"num\">(\d+)</td>",
            html,
            re.S,
        )
    }


def facts_total(html: str) -> tuple[int, int]:
    """Всего и показано фактов из HTML."""
    match = re.search(r"Всего фактов: (\d+), показано: (\d+)", html)
    if not match:
        fail("на экране фактов нет строки «Всего фактов»")
    return int(match.group(1)), int(match.group(2))


def pending_badge(html: str) -> int:
    """Счётчик «К подтверждению» из HTML."""
    match = re.search(r"К подтверждению \((\d+)\)", html)
    if not match:
        fail("на экране фактов нет кнопки «К подтверждению»")
    return int(match.group(1))


def review_state(html: str) -> tuple[int, int]:
    """Число спорных фактов и пар из HTML."""
    match = re.search(r"спорные факты \((\d+)\) и пары-кандидаты \((\d+)\)", html)
    if not match:
        fail("на экране ревью нет счётчиков спорных фактов и пар")
    return int(match.group(1)), int(match.group(2))


def review_pair_rows(html: str) -> list[dict]:
    """Строки пар-кандидатов из HTML."""
    return [
        {
            "id": match.group("id"),
            "text": _text(match.group("a") + " " + match.group("b")),
            "reason": _text(match.group("reason")),
        }
        for match in _PAIR_ROW_RE.finditer(html)
    ]


def review_pending_rows(html: str) -> list[dict]:
    """Строки фактов на подтверждение из HTML."""
    return [
        {"id": match.group("id"), "title": _text(match.group("title"))}
        for match in _PENDING_ROW_RE.finditer(html)
    ]


def progress_percent(html: str) -> int | None:
    """Процент прогресса из HTML или None."""
    match = re.search(r'role="progressbar".*?aria-valuenow="(\d+)"', html, re.S)
    return int(match.group(1)) if match else None


def badges_done(html: str) -> int:
    """Число завершённых бейджей на экране."""
    return html.count('class="badge done"')


def report_gaps(html: str) -> str:
    """Текст пробелов модели из HTML."""
    match = re.search(r'<div class="gaps">(.*?)</div>', html, re.S)
    return _text(match.group(1)) if match else ""


def report_metrics_md(markdown: str) -> dict[str, int]:
    """Метрики из markdown-отчёта."""
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    return {
        label.strip(): int(value)
        for label, value in re.findall(
            r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*$", markdown, re.M
        )
    }


def report_prompt_version(markdown: str) -> str:
    """Версия промптов из markdown-отчёта."""
    match = re.search(r"_Промпты LLM: версия (.+)_", markdown)
    return match.group(1).strip() if match else ""


def report_model_gaps(markdown: str) -> str:
    """Пробелы модели из markdown-отчёта."""
    match = re.search(r"\*\*Пробелы модели:\*\*\s*(.+)", markdown)
    return match.group(1).strip() if match else ""


def pg_engine(ctx: Acceptance):
    if ctx.engine is None:
        from services.common.db import get_engine

        ctx.engine = get_engine()
    if ctx.engine is None:
        fail("PostgreSQL недоступен: поднимите контейнер (make db-up)")
    return ctx.engine


def neo_driver(ctx: Acceptance):
    if ctx.driver is None:
        from services.common.graph_db import get_driver

        ctx.driver = get_driver()
    if ctx.driver is None:
        fail("Neo4j недоступен: поднимите контейнер (make db-up)")
    return ctx.driver


def pg_counts(engine) -> dict[str, int | None]:
    """Счётчики строк таблиц PostgreSQL."""
    from sqlalchemy import inspect, text

    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        counts: dict[str, int | None] = {}
        for table in _PG_TABLES:
            if table not in existing:
                counts[table] = None
                continue
            counts[table] = conn.execute(
                text(f'SELECT count(*) FROM "{table}"')
            ).scalar_one()
    return counts


def neo_total_counts(driver) -> dict[str, int]:
    """Число узлов и рёбер Neo4j."""
    with driver.session() as session:
        nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return {"nodes": int(nodes), "relationships": int(rels)}


def get_package(ctx: Acceptance, pid: str) -> dict:
    """Пакет из таблицы registry_packages."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, name, direction, documents, status, facts, last_run, "
                "started, reject_reason, files FROM registry_packages "
                "WHERE id = :pid"
            ),
            {"pid": pid},
        ).mappings().first()
    if row is None:
        return {}
    package = dict(row)
    package["files"] = _json(package.get("files"), [])
    return package


def find_package_id(ctx: Acceptance, name: str) -> str | None:
    """id пакета по имени."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        return conn.execute(
            text(
                "SELECT id FROM registry_packages WHERE name = :name "
                "ORDER BY seq DESC LIMIT 1"
            ),
            {"name": name},
        ).scalar()


def get_run(ctx: Acceptance, pid: str) -> dict:
    """Прогон из таблицы registry_runs."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        row = conn.execute(
            text(
                "SELECT state, started, finished, stages, metrics, progress, error "
                "FROM registry_runs WHERE package = :pid"
            ),
            {"pid": pid},
        ).mappings().first()
    if row is None:
        return {}
    run = dict(row)
    run["stages"] = _json(run.get("stages"), [])
    run["metrics"] = _json(run.get("metrics"), {})
    run["progress"] = _json(run.get("progress"), {})
    return run


def pg_package_counts(ctx: Acceptance, pid: str) -> dict[str, int]:
    """Счётчики пакета в PostgreSQL."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        chunks = conn.execute(
            text("SELECT count(*) FROM document_chunks WHERE package = :pid"),
            {"pid": pid},
        ).scalar_one()
        artifacts = conn.execute(
            text("SELECT count(*) FROM source_artifacts WHERE package = :pid"),
            {"pid": pid},
        ).scalar_one()
    return {"chunks": int(chunks), "artifacts": int(artifacts)}


def pg_chunks(ctx: Acceptance, pid: str) -> list[dict]:
    """Фрагменты пакета из PostgreSQL."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT chunk_id, chunk_index, artifact_id, content, "
                "start_offset, end_offset, content_hash "
                "FROM document_chunks WHERE package = :pid ORDER BY seq"
            ),
            {"pid": pid},
        ).mappings().all()
    return [dict(row) for row in rows]


def pg_artifacts(ctx: Acceptance, pid: str) -> list[dict]:
    """Артефакты пакета из PostgreSQL."""
    from sqlalchemy import text

    with pg_engine(ctx).connect() as conn:
        rows = conn.execute(
            text(
                "SELECT artifact_id, file_name, total_chunks, parsing_status "
                "FROM source_artifacts WHERE package = :pid ORDER BY seq"
            ),
            {"pid": pid},
        ).mappings().all()
    return [dict(row) for row in rows]


def neo_facts(ctx: Acceptance, pid: str) -> list[dict]:
    """Факты пакета из Neo4j."""
    with neo_driver(ctx).session() as session:
        rows = session.run(
            "MATCH (f:Fact {package: $pid}) "
            "RETURN f.id AS id, f.type AS type, f.title AS title, "
            "f.status AS status, f.confidence AS confidence, "
            "f.doc AS doc, f.frag AS frag "
            "ORDER BY toInteger(split(f.id, '-')[1])",
            pid=pid,
        )
        return [dict(row) for row in rows]


def neo_pairs(ctx: Acceptance, pid: str) -> list[dict]:
    """Пары пакета из Neo4j."""
    with neo_driver(ctx).session() as session:
        rows = session.run(
            "MATCH (a:Fact {package: $pid})-[p:PAIR]->(b:Fact {package: $pid}) "
            "RETURN p.id AS id, p.kind AS kind, p.reason AS reason, "
            "p.status AS status, a.id AS a, b.id AS b "
            "ORDER BY toInteger(split(p.id, '-')[1])",
            pid=pid,
        )
        return [dict(row) for row in rows]


def neo_graph_counts(ctx: Acceptance, pid: str) -> dict[str, int]:
    """Число фактов, источников и рёбер пакета в Neo4j."""
    with neo_driver(ctx).session() as session:
        def one(query: str, **params) -> int:
            return int(session.run(query, **params).single()[0])

        return {
            "facts": one(
                "MATCH (f:Fact {package: $pid}) RETURN count(f)", pid=pid
            ),
            "sources": one(
                "MATCH (:Fact {package: $pid})-[:EXTRACTED_FROM]->(s:Source) "
                "RETURN count(DISTINCT s)",
                pid=pid,
            ),
            "extracted": one(
                "MATCH (:Fact {package: $pid})-[:EXTRACTED_FROM]->() "
                "RETURN count(*)",
                pid=pid,
            ),
            "facts_without_source": one(
                "MATCH (f:Fact {package: $pid}) "
                "WHERE NOT (f)-[:EXTRACTED_FROM]->(:Source) RETURN count(f)",
                pid=pid,
            ),
            "relates": one(
                "MATCH (:Fact {package: $pid})-[r:RELATES]->() RETURN count(r)",
                pid=pid,
            ),
            "pairs": one(
                "MATCH (:Fact {package: $pid})-[p:PAIR]->() RETURN count(p)",
                pid=pid,
            ),
        }


def status_counts(facts: list[dict]) -> dict[str, int]:
    """Число фактов по статусам."""
    result: dict[str, int] = {}
    for fact in facts:
        status = str(fact.get("status") or "")
        result[status] = result.get(status, 0) + 1
    return result


def outbox_root() -> Path:
    """Корень outbox."""
    from services.builder import writer

    root = writer._root()
    return root if root.is_absolute() else REPO_ROOT / root


def outbox_files(pid: str) -> list[str]:
    """Файлы каркаса пакета."""
    root = outbox_root() / pid
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def upload_path(pid: str, document: Path) -> Path:
    """Путь загруженного документа в uploads."""
    return REPO_ROOT / "services" / "web_ui" / "data" / "uploads" / pid / document.name


# --- UI-сервер ---------------------------------------------------------------

class UiServer:
    """Запуск и остановка uvicorn в отдельном процессе."""

    def __init__(self, base_url: str, llm_mode: str) -> None:
        parsed = urlparse(base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 8000
        self.base_url = f"{parsed.scheme or 'http'}://{self.host}:{self.port}"
        self.llm_mode = llm_mode
        self.proc: subprocess.Popen | None = None
        self.log_file = None
        self.uvicorn_log = REPO_ROOT / "logs" / "acceptance_uvicorn.log"
        self.log_offset = 0

    def _app_log(self) -> Path:
        return REPO_ROOT / "logs" / "reqminer.log"

    def start(self) -> None:
        """Запускает uvicorn и ждёт готовности."""
        self.stop()
        deadline = time.monotonic() + 10
        while listening_pids(self.port) and time.monotonic() < deadline:
            time.sleep(0.5)
        if listening_pids(self.port):
            fail(
                f"порт {self.port} занят процессами {sorted(listening_pids(self.port))}: "
                "остановите старый UI (make stop)"
            )
        self.uvicorn_log.parent.mkdir(parents=True, exist_ok=True)
        app_log = self._app_log()
        self.log_offset = (
            len(app_log.read_text(encoding="utf-8", errors="replace"))
            if app_log.is_file()
            else 0
        )
        self.log_file = self.uvicorn_log.open(
            "a", encoding="utf-8", errors="replace"
        )
        self.log_file.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        if self.llm_mode == "offline":
            env["LLM_API_KEY"] = ""  # пустое значение перекрывает .env
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "services.web_ui.app:app",
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        self.proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        time.sleep(0.5)
        if self.proc.poll() is not None:
            fail(f"UI завершился при старте:\n{self.tail()}")
        self.wait_http()

    def stop(self) -> None:
        """Останавливает UI и освобождает порт."""
        run_cmd(
            [sys.executable, "scripts/ui_stop.py", str(self.port)],
            check=False,
        )
        deadline = time.monotonic() + 10
        while listening_pids(self.port) and time.monotonic() < deadline:
            time.sleep(0.5)
        if self.proc is not None:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None

    def wait_http(self, timeout: float = 60.0) -> None:
        """Ждёт ответа HTTP на базовом адресе."""
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                fail(f"UI завершился при старте:\n{self.tail()}")
            try:
                response = httpx.get(f"{self.base_url}/packages", timeout=2)
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 - ждём подъёма
                last_error = str(exc)
            time.sleep(1)
        fail(f"UI не поднялся за {timeout:.0f} с ({last_error})\n{self.tail()}")

    def tail(self, lines: int = 80) -> str:
        """Последние строки журнала для протокола."""
        parts = []
        for path in (REPO_ROOT / "logs" / "reqminer.log", self.uvicorn_log):
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                parts.append(f"--- {path.name} ---\n" + "\n".join(
                    content.splitlines()[-lines:]
                ))
        return "\n".join(parts)

    def wait_log(self, pattern: str, timeout: float = 90.0,
                 since: int | None = None) -> str:
        """Последняя новая строка журнала после offset, подходящая под шаблон."""
        deadline = time.monotonic() + timeout
        regex = re.compile(pattern)
        path = self._app_log()
        start = self.log_offset if since is None else since
        while time.monotonic() < deadline:
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                last = ""
                for line in content[start:].splitlines():
                    if regex.search(line):
                        last = line
                if last:
                    return last
            time.sleep(0.5)
        fail(f"в журнале нет строки /{pattern}/ за {timeout:.0f} с\n{self.tail()}")


def parse_backends(line: str) -> tuple[str, str, str]:
    """Разбирает строку стартового лога о бэкендах."""
    match = re.search(
        r"Хранилище Chunks: (\S+); реестр: (\S+); Knowledge: (\S+)", line
    )
    if not match:
        fail(f"не разобрана строка бэкендов: {line}")
    return match.group(1), match.group(2), match.group(3)


def parse_llm_line(line: str) -> str:
    """Режим LLM из стартового лога."""
    match = re.search(r"LLM-адаптер: (cloud|offline) режим", line)
    if not match:
        fail(f"не разобран режим LLM: {line}")
    return match.group(1)


def listening_pids(port: int) -> set[str]:
    """PID-ы процессов, слушающих порт (Windows netstat)."""
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pids: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if (
            len(parts) == 5
            and parts[0] == "TCP"
            and parts[3] == "LISTENING"
            and parts[1].endswith(f":{port}")
        ):
            pids.add(parts[4])
    return pids


# --- HTTP --------------------------------------------------------------------

def http_client(ctx: Acceptance) -> httpx.Client:
    """HTTP-клиент прогона."""
    if ctx.http is None:
        ctx.http = httpx.Client(
            base_url=ctx.args.base_url,
            timeout=60,
            follow_redirects=True,
        )
    return ctx.http


def get_page(ctx: Acceptance, url_path: str, **params) -> httpx.Response:
    """GET-запрос страницы."""
    response = http_client(ctx).get(url_path, params=params or None)
    if response.status_code != 200:
        fail(f"GET {url_path}: HTTP {response.status_code}\n{response.text[:500]}")
    return response


def post_form(ctx: Acceptance, path: str, fields: list[tuple[str, str]]):
    """POST формы с urlencoded-телом."""
    body = urlencode(fields).encode("utf-8")
    return http_client(ctx).post(
        path,
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


# --- этапы прогона -----------------------------------------------------------

def env_guard(args: argparse.Namespace) -> None:
    """Ловит пустые переменные окружения, из-за которых игнорируется .env."""
    for key in ("DATABASE_URL", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        if key in os.environ and not os.environ[key].strip():
            fail(
                f"{key} задан пустым в окружении: .env будет проигнорирован. "
                f"Выполните unset {key} или откройте новый shell."
            )
    if (
        args.llm_mode == "cloud"
        and "LLM_API_KEY" in os.environ
        and not os.environ["LLM_API_KEY"].strip()
    ):
        fail(
            "LLM_API_KEY задан пустым: облачный режим невозможен. "
            "Выполните unset LLM_API_KEY или используйте --llm-mode offline."
        )


def preflight(ctx: Acceptance) -> None:
    """Проверяет окружение, документ и доступность СУБД."""
    args = ctx.args
    ctx.document = args.document.resolve()
    if not ctx.document.is_file():
        fail(f"документ не найден: {ctx.document}")
    ctx.document_size = ctx.document.stat().st_size
    ctx.document_sha256 = sha256_file(ctx.document)
    ctx.commit = git_commit()
    ctx.command = " ".join([Path(sys.executable).name, *sys.argv])
    ctx.llm_mode = args.llm_mode
    ctx.protocol_path = resolve_protocol_path(args)
    env_guard(args)

    from services.common import settings

    settings.load()
    if settings.database_url() is None:
        fail("DATABASE_URL не задан: приёмка требует PostgreSQL")
    if settings.neo4j_uri() is None:
        fail("NEO4J_URI не задан: приёмка требует Neo4j")
    if args.llm_mode == "cloud" and not settings.llm_api_key():
        fail("LLM_API_KEY не задан: облачный режим недоступен")
    ctx.model = settings.llm_model()

    ctx.engine = pg_engine(ctx)
    ctx.driver = neo_driver(ctx)
    ctx.before_clean = {
        "postgres": pg_counts(ctx.engine),
        "neo4j": neo_total_counts(ctx.driver),
        "outbox_exists": outbox_root().is_dir(),
    }


def clean(ctx: Acceptance) -> None:
    """Очищает PostgreSQL, Neo4j, outbox и логи."""
    if ctx.args.no_clean:
        ctx.note("Очистка пропущена (--no-clean); БД и outbox могут содержать старые данные")
        return
    port = urlparse(ctx.args.base_url).port or 8000
    run_cmd([sys.executable, "scripts/ui_stop.py", str(port)], check=False)
    result = run_cmd(
        [sys.executable, "scripts/db_clean.py"], check=False
    )
    ctx.clean_output = (result.stdout + result.stderr).strip()
    ctx.after_clean = {
        "postgres": pg_counts(ctx.engine),
        "neo4j": neo_total_counts(ctx.driver),
        "outbox_exists": outbox_root().is_dir(),
    }
    if result.returncode != 0:
        fail(f"scripts/db_clean.py вернул {result.returncode}\n{ctx.clean_output}")
    dirty = {
        table: count
        for table, count in ctx.after_clean["postgres"].items()
        if count not in (0, None)
    }
    if dirty:
        fail(f"после очистки в PostgreSQL остались данные: {dirty}")
    if ctx.after_clean["neo4j"]["nodes"] or ctx.after_clean["neo4j"]["relationships"]:
        fail(f"после очистки в Neo4j остались данные: {ctx.after_clean['neo4j']}")
    ctx.check(
        "Базы очищены",
        not ctx.after_clean["outbox_exists"],
        "PostgreSQL и Neo4j пусты, outbox удалён"
        if not ctx.after_clean["outbox_exists"]
        else "outbox не удалён",
    )


def start(ctx: Acceptance) -> None:
    """Запускает UI и проверяет реальные бэкенды."""
    ctx.server = UiServer(ctx.args.base_url, ctx.args.llm_mode)
    ctx.server.start()
    ctx.backend_line = ctx.server.wait_log(r"Хранилище Chunks: .+")
    chunks, registry, knowledge = parse_backends(ctx.backend_line)
    ctx.check(
        "Реальные бэкенды",
        (chunks, registry, knowledge)
        == ("SqlChunkRepository", "SqlRegistry", "Neo4jKnowledgeRepository"),
        f"{chunks}; {registry}; {knowledge}",
    )
    empty = {
        "packages": get_page(ctx, "/packages").text,
        "facts": get_page(ctx, "/facts", package="2026-042").text,
        "report": get_page(ctx, "/report", package="2026-042").text,
    }
    ctx.empty_checks = {
        "packages": "Пакеты не найдены" in empty["packages"],
        "facts": "Факты не найдены" in empty["facts"],
        "report": "каркас ещё не сформирован" in empty["report"],
    }
    ctx.check(
        "Пустое приложение",
        all(ctx.empty_checks.values()),
        str(ctx.empty_checks),
    )


def upload(ctx: Acceptance) -> None:
    """Загружает документ через форму приёма."""
    args = ctx.args
    content = ctx.document.read_bytes()
    files = [("files", (ctx.document.name, content, "text/markdown"))]
    data = {
        "name": args.package_name,
        "direction": DIRECTION,
        "filetype-0": DOC_TYPE,
    }
    response = http_client(ctx).post(
        "/packages", data=data, files=files, follow_redirects=False
    )
    ctx.check(
        "Форма приёма принята",
        response.status_code == 303,
        f"HTTP {response.status_code}",
    )
    pid = find_package_id(ctx, args.package_name)
    if not pid:
        fail(f"пакет «{args.package_name}» не появился в реестре")
    ctx.pid = pid
    ctx.package = get_package(ctx, pid)
    ctx.check("Один документ в пакете", ctx.package.get("documents") == 1)
    ctx.check(
        "Пакет не отклонён",
        ctx.package.get("status") != "reject",
        str(ctx.package.get("reject_reason") or ""),
    )


def wait_terminal(ctx: Acceptance, timeout: float | None = None) -> dict:
    """Ждёт завершения прогона и возвращает его запись."""
    deadline = time.monotonic() + (timeout or ctx.args.timeout)
    last: dict = {}
    while time.monotonic() < deadline:
        last = get_run(ctx, ctx.pid or "")
        if last:
            state = last.get("state")
            if state == "failed":
                fail(f"прогон упал: {last.get('error') or 'см. журнал'}")
            if state in ("confirm", "done"):
                return last
        time.sleep(POLL_SECONDS)
    fail(
        f"прогон не завершился за {timeout or ctx.args.timeout:.0f} с; "
        f"последнее состояние: {last.get('state')}"
    )
    return last  # для типизации


def first_run(ctx: Acceptance) -> None:
    """Проверяет первый прогон: факты, пары, прогресс и метрики."""
    started = time.monotonic()
    first = wait_terminal(ctx)
    ctx.first_run = first
    ctx.run = first
    ctx.first_duration = time.monotonic() - started
    ctx.facts = neo_facts(ctx, ctx.pid or "")
    ctx.pairs = neo_pairs(ctx, ctx.pid or "")
    ctx.chunks = pg_chunks(ctx, ctx.pid or "")
    ctx.artifacts = pg_artifacts(ctx, ctx.pid or "")
    statuses = status_counts(ctx.facts)
    ctx.first_pending = statuses.get("pending_review", 0)
    ctx.first_open_pairs = sum(
        1 for pair in ctx.pairs if pair.get("status") == "open"
    )

    stages = first.get("stages") or []
    ctx.check(
        "Четыре этапа завершены",
        len(stages) == 4
        and all(stage.get("status") == "done" for stage in stages),
        str([stage.get("status") for stage in stages]),
    )
    metrics = first.get("metrics") or {}
    ctx.check(
        "Фрагментов ровно один",
        metrics.get("fragments") == 1,
        f"fragments={metrics.get('fragments')}",
    )
    ctx.check(
        "Фактов не меньше одного",
        len(ctx.facts) >= 1,
        f"фактов={len(ctx.facts)}",
    )
    ctx.check(
        "Карантин пуст",
        metrics.get("quarantine", 0) == 0,
        f"quarantine={metrics.get('quarantine')}",
    )
    ctx.check(
        "Трассировка фактов",
        all(
            fact.get("doc") == ctx.document.name and fact.get("frag") == 1
            for fact in ctx.facts
        ),
        f"doc={ctx.document.name}, frag=1",
    )

    ctx.panel_html = get_page(ctx, f"/packages/{ctx.pid}/run/panel").text
    ctx.check(
        "Панель: четыре этапа",
        badges_done(ctx.panel_html) == 4,
        f"badge done={badges_done(ctx.panel_html)}",
    )
    percent = progress_percent(ctx.panel_html)
    ctx.check("Панель: 100 %", percent == 100, f"percent={percent}")

    ctx.facts_html = get_page(ctx, "/facts", package=ctx.pid).text
    total, shown = facts_total(ctx.facts_html)
    ctx.check(
        "Экран фактов",
        total == len(ctx.facts) and shown == len(ctx.facts),
        f"total={total}, shown={shown}, facts={len(ctx.facts)}",
    )
    ctx.check(
        "Счётчик подтверждения",
        pending_badge(ctx.facts_html) == ctx.first_pending,
        f"badge={pending_badge(ctx.facts_html)}, pending={ctx.first_pending}",
    )

    if ctx.facts:
        fact_id = ctx.facts[0]["id"]
        fragment = get_page(
            ctx, f"/facts/{fact_id}/fragment", package=ctx.pid
        )
        payload = fragment.json()
        ctx.check(
            "Фрагмент-источник доступен",
            bool(payload.get("text"))
            and "Техническое задание" in payload.get("text", ""),
            f"title={payload.get('title')!r}",
        )

    ctx.review_html = get_page(ctx, "/review", package=ctx.pid).text
    ctx.review_state = review_state(ctx.review_html)
    open_pair_ids = {
        pair["id"] for pair in ctx.pairs if pair.get("status") == "open"
    }
    facts_in_pairs = {
        fact_id
        for pair in ctx.pairs
        if pair.get("status") == "open"
        for fact_id in (pair.get("a"), pair.get("b"))
    }
    expected_review_pending = sum(
        1
        for fact in ctx.facts
        if fact.get("status") in ("pending_review", "needs_clarification")
        and fact.get("id") not in facts_in_pairs
    )
    ctx.check(
        "Экран ревью",
        ctx.review_state == (expected_review_pending, len(open_pair_ids)),
        f"{ctx.review_state}, ожидалось "
        f"({expected_review_pending}, {len(open_pair_ids)})",
    )

    try:
        ctx.llm_line = ctx.server.wait_log(
            r"LLM-адаптер: (cloud|offline) режим", timeout=15
        )
        actual_mode = parse_llm_line(ctx.llm_line)
        ctx.check(
            "Режим LLM",
            actual_mode == ctx.args.llm_mode,
            f"ожидался {ctx.args.llm_mode}, получен {actual_mode}",
        )
    except AcceptanceError:
        ctx.llm_line = ""
        ctx.note(
            "Строка LLM-адаптера не найдена в новом журнале; "
            "для облачного режима он подтверждается версией промптов в отчёте"
        )
    if "откат на детерминированные правила" in (ctx.server.tail(400) or ""):
        ctx.note("В журнале есть fallback на offline-правила — проверьте качество облачного ответа")


def decide_pair_action(pair: dict) -> str:
    """Действие по паре: duplicate/contradiction по причине, иначе dismiss."""
    reason = (pair.get("reason") or "").lower()
    kind = pair.get("kind")
    if "совпадающий смысл" in reason or kind == "duplicate":
        return "pair_duplicate"
    if "разные значения" in reason or kind == "contradiction":
        return "pair_contradiction"
    return "pair_dismiss"


def review(ctx: Acceptance) -> None:
    """Подтверждает факты и разрешает пары через UI."""
    ctx.review_before = status_counts(ctx.facts)
    ctx.review_after = status_counts(ctx.facts)
    if ctx.first_run.get("state") == "done":
        ctx.note("Фактов в pending_review нет — ревью пропущено")
        return
    open_pairs = [pair for pair in ctx.pairs if pair.get("status") == "open"]
    for pair in open_pairs:
        action = decide_pair_action(pair)
        response = post_form(
            ctx,
            "/review/pairs",
            [
                ("package", ctx.pid or ""),
                ("action", action),
                ("pair_id", pair["id"]),
            ],
        )
        ctx.check(
            f"Пара {pair['id']}",
            response.status_code == 303,
            f"{pair.get('kind')} → {action}, HTTP {response.status_code}",
        )
        ctx.pair_actions.append(
            {
                "id": pair["id"],
                "kind": pair.get("kind"),
                "reason": pair.get("reason"),
                "a": pair.get("a"),
                "b": pair.get("b"),
                "action": action,
            }
        )

    ctx.pairs = neo_pairs(ctx, ctx.pid or "")
    open_after = [pair for pair in ctx.pairs if pair.get("status") == "open"]
    ctx.check(
        "Открытых пар нет",
        not open_after,
        f"осталось {len(open_after)}",
    )

    # решения по парам могли изменить статусы фактов - перечитываем
    ctx.facts = neo_facts(ctx, ctx.pid or "")
    pending = [
        fact for fact in ctx.facts if fact.get("status") == "pending_review"
    ]
    if pending:
        fields = [
            ("package", ctx.pid or ""),
            ("action", "confirm"),
            *[(("fact_id"), fact["id"]) for fact in pending],
        ]
        response = post_form(ctx, "/review/facts", fields)
        ctx.check(
            "Факты подтверждены",
            response.status_code == 303,
            f"подтверждено {len(pending)}, HTTP {response.status_code}",
        )

    ctx.facts = neo_facts(ctx, ctx.pid or "")
    ctx.review_after = status_counts(ctx.facts)
    ctx.check(
        "pending_review пуст",
        ctx.review_after.get("pending_review", 0) == 0,
        str(ctx.review_after),
    )


def trigger_analyze(ctx: Acceptance) -> None:
    """Запускает повторный анализ пакета."""
    response = http_client(ctx).post(
        f"/packages/{ctx.pid}/analyze", follow_redirects=False
    )
    if response.status_code == 409:
        wait_terminal(ctx)
        response = http_client(ctx).post(
            f"/packages/{ctx.pid}/analyze", follow_redirects=False
        )
    ctx.check(
        "Повторный анализ запущен",
        response.status_code == 303,
        f"HTTP {response.status_code}",
    )


def wait_rerun(ctx: Acceptance, before: dict) -> dict:
    """Ждёт повторный прогон и возвращает его запись."""
    deadline = time.monotonic() + ctx.args.timeout
    before_finished = before.get("finished")
    while time.monotonic() < deadline:
        run = get_run(ctx, ctx.pid or "")
        if run:
            if run.get("state") == "failed":
                fail(f"повторный прогон упал: {run.get('error') or 'см. журнал'}")
            if run.get("state") == "done":
                if before.get("state") != "done":
                    return run
                if run.get("finished") != before_finished:
                    return run
        time.sleep(POLL_SECONDS)
    fail("повторный прогон не завершился")


def rerun(ctx: Acceptance) -> None:
    """Проверяет повторный анализ после ревью."""
    before = get_run(ctx, ctx.pid or "")
    started = time.monotonic()
    trigger_analyze(ctx)
    run = wait_rerun(ctx, before)
    ctx.second_run = run
    ctx.run = run
    ctx.second_duration = time.monotonic() - started
    if run.get("state") != "done":
        fail(f"после повторного анализа состояние {run.get('state')}, ожидалось done")

    facts_after = neo_facts(ctx, ctx.pid or "")
    pairs_after = neo_pairs(ctx, ctx.pid or "")
    ctx.check(
        "Факты не задублировались",
        len(facts_after) == len(ctx.facts),
        f"было {len(ctx.facts)}, стало {len(facts_after)}",
    )
    ctx.check(
        "Статусы фактов сохранены",
        status_counts(facts_after) == ctx.review_after,
        f"было {ctx.review_after}, стало {status_counts(facts_after)}",
    )
    ctx.check(
        "Пары не задублировались",
        len(pairs_after) == len(ctx.pairs),
        f"было {len(ctx.pairs)}, стало {len(pairs_after)}",
    )
    ctx.facts = facts_after
    ctx.pairs = pairs_after
    ctx.package = get_package(ctx, ctx.pid or "")
    ctx.check(
        "Пакет: каркас сформирован",
        ctx.package.get("status") == "done",
        str(ctx.package.get("status")),
    )
    metrics = run.get("metrics") or {}
    ctx.check(
        "Метрики повторного прогона",
        metrics.get("pending") == 0
        and metrics.get("facts") == len(ctx.facts),
        f"pending={metrics.get('pending')}, facts={metrics.get('facts')}",
    )


def expected_report_metrics(ctx: Acceptance) -> dict[str, int]:
    """Ожидаемые метрики аналитического отчёта."""
    metrics = ctx.run.get("metrics") or {}
    return {
        "documents": int(ctx.package.get("documents") or 0),
        "fragments": int(metrics.get("fragments") or 0),
        "facts": len(ctx.facts),
        "confirmed": sum(
            1 for fact in ctx.facts if fact.get("status") == "confirmed"
        ),
        "pending": sum(
            1 for fact in ctx.facts if fact.get("status") == "pending_review"
        ),
        "pairs_contradiction": sum(
            1 for pair in ctx.pairs if pair.get("kind") == "contradiction"
        ),
        "pairs_duplicate": sum(
            1 for pair in ctx.pairs if pair.get("kind") == "duplicate"
        ),
        "quarantine": int(metrics.get("quarantine") or 0),
    }


def expected_sections(ctx: Acceptance) -> dict[str, int]:
    """Ожидаемое число фактов в разделах каркаса."""
    from services.builder.planner import OUTBOX_SECTIONS

    return {
        section["title"]: sum(
            1 for fact in ctx.facts if fact.get("type") in section["types"]
        )
        for section in OUTBOX_SECTIONS
    }


def report(ctx: Acceptance) -> None:
    """Проверяет экран отчёта, каркас и архивы."""
    from services.builder.planner import (
        FILE_TITLES,
        TYPE_TO_FILE,
        gaps,
        gaps_text,
    )

    ctx.report_html = get_page(ctx, "/report", package=ctx.pid).text
    ctx.report_sections = html_sections(ctx.report_html)
    ctx.check(
        "Пять разделов отчёта",
        len(ctx.report_sections) == 5,
        str(ctx.report_sections),
    )
    ctx.check(
        "Счётчики разделов",
        ctx.report_sections == expected_sections(ctx),
        f"{ctx.report_sections} != {expected_sections(ctx)}",
    )
    raw_metrics = html_metrics(ctx.report_html)
    html_labels = {
        "documents": "документа",
        "fragments": "фрагмента",
        "facts": "фактов",
        "confirmed": "подтверждено аналитиком",
        "pending": "ожидает подтверждения",
        "pairs_contradiction": "пара противоречий",
        "pairs_duplicate": "пара дубликатов",
        "quarantine": "карантин",
    }
    expected_html = expected_report_metrics(ctx)
    ctx.report_metrics = {
        key: int(raw_metrics.get(label, -1)) for key, label in html_labels.items()
    }
    ctx.check(
        "Метрики экрана отчёта",
        ctx.report_metrics == expected_html,
        f"{ctx.report_metrics} != {expected_html}",
    )
    ctx.report_gaps = report_gaps(ctx.report_html)
    expected_gaps = gaps_text(ctx.facts)
    ctx.check(
        "Пробелы модели",
        ctx.report_gaps == expected_gaps,
        f"{ctx.report_gaps!r} != {expected_gaps!r}",
    )

    preview = get_page(ctx, "/report/preview", package=ctx.pid).text
    missing_titles = [
        title for title in FILE_TITLES.values() if title not in preview
    ]
    ctx.check(
        "Предпросмотр всех разделов",
        not missing_titles,
        f"нет: {missing_titles}",
    )
    for rel_path in SECTION_FILES:
        page = get_page(
            ctx, "/report/preview", package=ctx.pid, path=rel_path
        )
        ctx.check(
            f"Предпросмотр {rel_path}",
            bool(page.text.strip()),
            f"{len(page.text)} символов",
        )

    archive = get_page(ctx, "/report/export/md", package=ctx.pid)
    ctx.check(
        "Экспорт ZIP",
        archive.headers.get("content-type") == "application/zip",
        archive.headers.get("content-type", ""),
    )
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        ctx.zip_names = sorted(
            name for name in zf.namelist() if not name.endswith("/")
        )
        ctx.report_md = zf.read("analysis_report.md").decode("utf-8")
        ctx.zip_sha256 = sha256_bytes(archive.content)
    ctx.check(
        "Восемь файлов каркаса",
        set(ctx.zip_names) == set(EXPECTED_ZIP_NAMES),
        str(ctx.zip_names),
    )

    md_metrics = report_metrics_md(ctx.report_md)
    md_labels = {
        "documents": "документов",
        "fragments": "фрагментов",
        "facts": "фактов",
        "confirmed": "подтверждено аналитиком",
        "pending": "ожидает подтверждения",
        "pairs_contradiction": "пара противоречий",
        "pairs_duplicate": "пара дубликатов",
        "quarantine": "карантин",
    }
    parsed_md = {
        key: int(md_metrics.get(label, -1)) for key, label in md_labels.items()
    }
    ctx.check(
        "Метрики analysis_report.md",
        parsed_md == expected_html,
        f"{parsed_md} != {expected_html}",
    )
    ctx.report_prompt = report_prompt_version(ctx.report_md)
    if ctx.args.llm_mode == "cloud":
        ctx.check(
            "Облачные промпты зафиксированы",
            bool(ctx.report_prompt),
            f"версия={ctx.report_prompt!r}",
        )
    else:
        ctx.note("Offline-режим: версия промптов в отчёт не пишется")

    expected_model_gaps = gaps(ctx.facts)
    actual_model_gaps = report_model_gaps(ctx.report_md)
    ctx.check(
        "Пробелы в analysis_report.md",
        actual_model_gaps == (expected_model_gaps or ""),
        f"{actual_model_gaps!r} != {expected_model_gaps!r}",
    )

    included = [
        fact for fact in ctx.facts if fact.get("status") not in EXCLUDED_STATUSES
    ]
    for rel_path in SECTION_FILES:
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
            text = zf.read(rel_path).decode("utf-8")
        title = FILE_TITLES[rel_path]
        ctx.check(
            f"Заголовок {rel_path}",
            text.startswith(f"# {title}"),
            text.splitlines()[0] if text else "",
        )
        types = [
            fact_type
            for fact_type, target in TYPE_TO_FILE.items()
            if target == rel_path
        ]
        filled = [fact for fact in included if fact.get("type") in types]
        if not filled:
            ctx.check(
                f"Заглушка {rel_path}",
                "не извлечены" in text or "раздел пуст" in text,
                "пустой раздел должен содержать причину",
            )
        else:
            body = text.split("\n", 1)[1].strip() if "\n" in text else ""
            ctx.check(
                f"Раздел заполнен {rel_path}",
                bool(body),
                f"фактов: {len(filled)}",
            )
            if ctx.args.llm_mode == "cloud" and not re.search(
                r"источник|фрагмент|достоверность|F-\d+", body, re.I
            ):
                ctx.note(f"{rel_path}: модель не сохранила трассировку в тексте")

    download = get_page(ctx, "/report/download", package=ctx.pid)
    ctx.check(
        "Скачивание отчёта",
        "text/markdown" in download.headers.get("content-type", "")
        and f"| фактов | {len(ctx.facts)} |" in download.text,
        download.headers.get("content-type", ""),
    )


def graph(ctx: Acceptance) -> None:
    """Проверяет граф требований и его счётчики."""
    ctx.graph_data = get_page(
        ctx, "/graph/data", package=ctx.pid
    ).json()
    nodes = ctx.graph_data.get("nodes") or []
    edges = ctx.graph_data.get("edges") or []
    fact_nodes = [node for node in nodes if node.get("kind") == "fact"]
    source_nodes = [node for node in nodes if node.get("kind") == "source"]
    trace_edges = [
        edge for edge in edges if edge.get("type") == "извлечен из"
    ]
    ctx.check(
        "Узлы-факты графа",
        len(fact_nodes) == len(ctx.facts),
        f"узлов={len(fact_nodes)}, фактов={len(ctx.facts)}",
    )
    ctx.check(
        "Трассировка всех фактов",
        len(trace_edges) == len(ctx.facts)
        and len(source_nodes) >= 1,
        f"рёбер={len(trace_edges)}, источников={len(source_nodes)}",
    )
    ctx.graph_html = get_page(ctx, "/graph", package=ctx.pid).text
    match = re.search(r"\((\d+) узлов, (\d+) связей\)", ctx.graph_html)
    if not match:
        fail("на экране графа нет счётчика узлов и связей")
    ctx.check(
        "Счётчики графа",
        int(match.group(1)) == len(fact_nodes)
        and int(match.group(2)) == len(edges),
        f"HTML={match.groups()}, JSON=({len(fact_nodes)}, {len(edges)})",
    )


def snapshot(ctx: Acceptance) -> dict:
    """Снимок состояния для проверки персистентности."""
    archive = get_page(ctx, "/report/export/md", package=ctx.pid)
    return {
        "package": get_package(ctx, ctx.pid or ""),
        "run": get_run(ctx, ctx.pid or ""),
        "facts": neo_facts(ctx, ctx.pid or ""),
        "pairs": neo_pairs(ctx, ctx.pid or ""),
        "pg": pg_package_counts(ctx, ctx.pid or ""),
        "neo": neo_graph_counts(ctx, ctx.pid or ""),
        "zip_names": sorted(
            name
            for name in zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
            if not name.endswith("/")
        ),
        "zip_sha256": sha256_bytes(archive.content),
        "outbox": outbox_files(ctx.pid or ""),
        "upload_exists": upload_path(ctx.pid or "", ctx.document).is_file(),
    }


def persistence(ctx: Acceptance) -> None:
    """Проверяет, что данные переживают перезапуск UI."""
    ctx.persistence_before = snapshot(ctx)
    ctx.server.stop()
    ctx.server.start()
    if ctx.http is not None:
        ctx.http.close()
        ctx.http = None
    backend_line = ctx.server.wait_log(r"Хранилище Chunks: .+")
    chunks, registry, knowledge = parse_backends(backend_line)
    ctx.check(
        "После рестарта: реальные бэкенды",
        (chunks, registry, knowledge)
        == ("SqlChunkRepository", "SqlRegistry", "Neo4jKnowledgeRepository"),
        f"{chunks}; {registry}; {knowledge}",
    )
    ctx.persistence_after = snapshot(ctx)
    before, after = ctx.persistence_before, ctx.persistence_after
    ctx.check("Пакет сохранился", before["package"] == after["package"])
    ctx.check("Прогон сохранился", before["run"] == after["run"])
    ctx.check(
        "Факты сохранились",
        before["facts"] == after["facts"],
        f"{len(before['facts'])} фактов",
    )
    ctx.check("Пары сохранились", before["pairs"] == after["pairs"])
    ctx.check(
        "Каркас сохранился",
        before["zip_names"] == after["zip_names"]
        and before["zip_sha256"] == after["zip_sha256"],
        f"{len(after['zip_names'])} файлов",
    )
    ctx.check(
        "Исходник на месте",
        before["upload_exists"] and after["upload_exists"],
        str(upload_path(ctx.pid or "", ctx.document)),
    )

    facts_page = get_page(ctx, "/facts", package=ctx.pid).text
    total, shown = facts_total(facts_page)
    ctx.check(
        "HTTP после рестарта: факты",
        total == len(ctx.facts) and shown == len(ctx.facts),
        f"{total}/{shown}",
    )
    report_page = get_page(ctx, "/report", package=ctx.pid).text
    ctx.check(
        "HTTP после рестарта: отчёт",
        "Каркас технической документации" in report_page,
    )
    graph_page = get_page(ctx, "/graph/data", package=ctx.pid).json()
    ctx.check(
        "HTTP после рестарта: граф",
        len([n for n in graph_page.get("nodes", []) if n.get("kind") == "fact"])
        == len(ctx.facts),
    )


def upload_invalid(ctx: Acceptance) -> dict:
    """Загружает недопустимый файл для негативной проверки."""
    payload_path = REPO_ROOT / "demo" / "outbox-2026-043.zip"
    payload = payload_path.read_bytes() if payload_path.is_file() else b"%PDF-1.4"
    files = [("files", ("scan.pdf", payload, "application/pdf"))]
    data = {
        "name": "Скан ТЗ (приёмка)",
        "direction": DIRECTION,
        "filetype-0": DOC_TYPE,
    }
    response = http_client(ctx).post(
        "/packages", data=data, files=files, follow_redirects=False
    )
    pid = find_package_id(ctx, "Скан ТЗ (приёмка)")
    package = get_package(ctx, pid or "")
    return {
        "response": response.status_code,
        "pid": pid,
        "package": package,
        "run_html": get_page(ctx, f"/packages/{pid}/run").text if pid else "",
        "report_html": get_page(
            ctx, "/report", package=pid or "2026-042"
        ).text,
    }


def negative(ctx: Acceptance) -> None:
    """Прогоняет негативные проверки формы приёма."""
    invalid = upload_invalid(ctx)
    ctx.negative.append({"case": "недопустимый формат", **invalid})
    ctx.check(
        "Недопустимый формат отклонён",
        invalid["response"] == 303
        and invalid["package"].get("status") == "reject"
        and invalid["package"].get("documents") == 0
        and invalid["package"].get("reject_reason") == "недопустимый формат",
        f"pid={invalid['pid']}, "
        f"{invalid['package'].get('status')}/{invalid['package'].get('reject_reason')}",
    )
    ctx.check(
        "Экран отклонённого прогона",
        "прогон отклонен" in invalid["run_html"],
    )
    ctx.check(
        "Отчёт отклонённого пакета",
        "каркас ещё не сформирован" in invalid["report_html"],
    )

    response = http_client(ctx).post(
        "/packages",
        data={"name": "Пустая форма (приёмка)", "direction": DIRECTION},
        follow_redirects=True,
    )
    pid = find_package_id(ctx, "Пустая форма (приёмка)")
    package = get_package(ctx, pid or "")
    ctx.negative.append(
        {
            "case": "пустая форма",
            "response": response.status_code,
            "pid": pid,
            "package": package,
        }
    )
    ctx.check(
        "Пустая форма отклонена",
        response.status_code == 200
        and package.get("status") == "reject"
        and package.get("reject_reason") == "файлы не выбраны",
        f"HTTP {response.status_code}, "
        f"{package.get('status')}/{package.get('reject_reason')}",
    )


# --- протокол ----------------------------------------------------------------

def resolve_protocol_path(args: argparse.Namespace) -> Path:
    """Выбирает путь протокола по аргументам."""
    if args.protocol:
        path = Path(args.protocol)
        return path if path.is_absolute() else REPO_ROOT / path
    return (
        REPO_ROOT
        / "docs"
        / "plans"
        / f"acceptance_protocol_calculator_{datetime.now():%Y-%m-%d}.md"
    )


def write_protocol(ctx: Acceptance, verdict: str) -> Path:
    """Пишет markdown-протокол прогона."""
    path = ctx.protocol_path or resolve_protocol_path(ctx.args)
    if path.exists() and not ctx.args.force:
        stamp = datetime.now().strftime("%H%M%S")
        path = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)

    def metric_rows(metrics: dict[str, Any]) -> list[list[Any]]:
        labels = {
            "documents": "документов",
            "fragments": "фрагментов",
            "facts": "фактов",
            "confirmed": "подтверждено аналитиком",
            "pending": "ожидает подтверждения",
            "pairs_contradiction": "пара противоречий",
            "pairs_duplicate": "пара дубликатов",
            "quarantine": "карантин",
        }
        return [[label, metrics.get(key, "—")] for key, label in labels.items()]

    facts_rows = [
        [
            fact.get("id"),
            fact.get("type"),
            fact.get("status"),
            fact.get("confidence"),
            fact.get("doc"),
            fact.get("frag"),
            fact.get("title"),
        ]
        for fact in ctx.facts
    ]
    pairs_rows = [
        [
            pair.get("id"),
            pair.get("kind"),
            pair.get("status"),
            pair.get("a"),
            pair.get("b"),
            pair.get("reason"),
        ]
        for pair in ctx.pairs
    ]
    action_rows = [
        [
            action["id"],
            action["kind"],
            action["action"],
            action["reason"],
        ]
        for action in ctx.pair_actions
    ]
    checks_rows = [
        [index, check.name, "PASS" if check.ok else "FAIL", check.detail]
        for index, check in enumerate(ctx.checks, start=1)
    ]
    negative_rows = [
        [
            item.get("case"),
            item.get("pid"),
            item.get("package", {}).get("status"),
            item.get("package", {}).get("reject_reason"),
        ]
        for item in ctx.negative
    ]
    sections_rows = [
        [title, count] for title, count in (ctx.report_sections or {}).items()
    ]
    persistence_rows = []
    before = ctx.persistence_before or {}
    after = ctx.persistence_after or {}
    if not before or not after:
        persistence_rows.append(["—", "—", "—", "не выполнялась"])
    for key in ("facts", "pairs"):
        if before and after:
            persistence_rows.append(
                [
                    key,
                    len(before.get(key, [])),
                    len(after.get(key, [])),
                    "PASS"
                    if len(before.get(key, [])) == len(after.get(key, []))
                    else "FAIL",
                ]
            )
    for key in ("chunks", "artifacts"):
        if before and after:
            persistence_rows.append(
                [
                    key,
                    before.get("pg", {}).get(key),
                    after.get("pg", {}).get(key),
                    "PASS"
                    if before.get("pg", {}).get(key)
                    == after.get("pg", {}).get(key)
                    else "FAIL",
                ]
            )
    if before and after:
        persistence_rows.append(
            [
                "zip",
                f"{len(before.get('zip_names', []))} файлов",
                f"{len(after.get('zip_names', []))} файлов",
                "PASS"
                if before.get("zip_sha256") == after.get("zip_sha256")
                else "FAIL",
            ]
        )

    lines = [
        "# Протокол приёмочного прогона: `демо/калькулятор.md`",
        "",
        f"**Дата:** {ctx.started_at:%Y-%m-%d %H:%M:%S}  ",
        f"**Ветка/коммит:** `{ctx.commit}`  ",
        f"**Команда:** `{ctx.command}`  ",
        f"**Итог:** **{verdict}**  ",
        "",
        "## 1. Условия",
        "",
        md_table(
            ["Параметр", "Значение"],
            [
                ["Документ", f"`{ctx.document}`"],
                ["Размер", f"{ctx.document_size} байт"],
                ["SHA-256", f"`{ctx.document_sha256}`"],
                ["Base URL", ctx.args.base_url],
                ["LLM-режим", ctx.args.llm_mode],
                ["Модель", ctx.model or "—"],
                ["Python", sys.version.split()[0]],
                ["ОС", os.name],
            ],
        ),
        "",
        "## 2. Очистка",
        "",
        "Команда: `make clean` (эквивалент `scripts/db_clean.py`).",
        "",
        md_table(
            ["Хранилище", "До", "После"],
            [
                [
                    table,
                    (ctx.before_clean.get("postgres", {}) or {}).get(table),
                    (ctx.after_clean.get("postgres", {}) or {}).get(table),
                ]
                for table in _PG_TABLES
            ]
            + [
                [
                    "Neo4j узлов",
                    (ctx.before_clean.get("neo4j", {}) or {}).get("nodes"),
                    (ctx.after_clean.get("neo4j", {}) or {}).get("nodes"),
                ],
                [
                    "Neo4j связей",
                    (ctx.before_clean.get("neo4j", {}) or {}).get("relationships"),
                    (ctx.after_clean.get("neo4j", {}) or {}).get("relationships"),
                ],
                [
                    "outbox существует",
                    ctx.before_clean.get("outbox_exists"),
                    ctx.after_clean.get("outbox_exists"),
                ],
            ],
        ),
        "",
        "## 3. Запуск",
        "",
        f"Строка бэкендов: `{ctx.backend_line or '—'}`  ",
        f"Строка LLM: `{ctx.llm_line or '—'}`  ",
        f"Пустое приложение: `{ctx.empty_checks}`",
        "",
        "## 4. Приём документа",
        "",
        md_table(
            ["Параметр", "Значение"],
            [
                ["Имя пакета", ctx.args.package_name],
                ["ID пакета", ctx.pid or "—"],
                ["Документов", ctx.package.get("documents")],
                ["Статус", ctx.package.get("status")],
            ],
        ),
        "",
        "## 5. Первый прогон",
        "",
        f"Длительность: **{ctx.first_duration:.1f} с**  ",
        f"Состояние: `{ctx.first_run.get('state')}`  ",
        f"Метрики: `{json.dumps(ctx.first_run.get('metrics', {}), ensure_ascii=False)}`",
        "",
        md_table(["Факт", "Тип", "Статус", "Достоверность", "Документ", "Фрагмент", "Формулировка"], facts_rows)
        if facts_rows
        else "_Факты не извлечены._",
        "",
        md_table(["Пара", "Вид", "Статус", "A", "B", "Причина"], pairs_rows)
        if pairs_rows
        else "_Пар-кандидатов нет._",
        "",
        "## 6. Ревью",
        "",
        f"Статусы до: `{ctx.review_before}`  ",
        f"Статусы после: `{ctx.review_after}`",
        "",
        md_table(["Пара", "Вид", "Действие", "Причина"], action_rows)
        if action_rows
        else "_Открытых пар не было._",
        "",
        "## 7. Повторный анализ",
        "",
        f"Длительность: **{ctx.second_duration:.1f} с**  ",
        f"Состояние: `{ctx.second_run.get('state')}`  ",
        f"Статус пакета: `{ctx.package.get('status')}`  ",
        f"Метрики: `{json.dumps(ctx.second_run.get('metrics', {}), ensure_ascii=False)}`",
        "",
        "## 8. Каркас и отчёт",
        "",
        md_table(["Раздел", "Фактов"], sections_rows)
        if sections_rows
        else "_Разделы не получены._",
        "",
        md_table(["Метрика", "Значение"], metric_rows(ctx.report_metrics)),
        "",
        f"Пробелы модели: `{ctx.report_gaps}`  ",
        f"Версия промптов: `{ctx.report_prompt or '—'}`",
        "",
        f"Файлы ZIP: `{ctx.zip_names}`",
        "",
        "## 9. Граф",
        "",
        md_table(
            ["Показатель", "Значение"],
            [
                ["Узлы-факты", len([n for n in (ctx.graph_data.get("nodes") or []) if n.get("kind") == "fact"])],
                ["Узлы-источники", len([n for n in (ctx.graph_data.get("nodes") or []) if n.get("kind") == "source"])],
                ["Связи", len(ctx.graph_data.get("edges") or [])],
            ],
        ),
        "",
        "## 10. Персистентность",
        "",
        md_table(["Показатель", "До рестарта", "После рестарта", "Результат"], persistence_rows),
        "",
        "## 11. Негативные проверки",
        "",
        md_table(["Случай", "ID", "Статус", "Причина"], negative_rows)
        if negative_rows
        else "_Не выполнялись._",
        "",
        "## 12. Итог",
        "",
        md_table(["#", "Проверка", "Результат", "Детали"], checks_rows)
        if checks_rows
        else "_Проверки не выполнялись._",
        "",
    ]
    if ctx.error:
        lines += [
            "### Ошибка",
            "",
            "```text",
            ctx.error,
            "```",
            "",
        ]
    if ctx.notes:
        lines += ["### Замечания", ""] + [f"- {note}" for note in ctx.notes] + [""]
    lines += [
        "### Ограничения",
        "",
        "- Облачный LLM недетерминирован: числа и текст зависят от модели.",
        "- Известное расхождение `/report` и артефакта (дубликаты в счётчике) не исправлялось.",
        "- `make clean` удаляет `outbox/` и `logs/`; `demo/outbox-2026-043.zip` не затрагивается.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- CLI -----------------------------------------------------------------────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разбирает аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Полный приёмочный прогон на реальных PostgreSQL/Neo4j: "
            "очистка, загрузка demo/калькулятор.md, ревью, повторный анализ, "
            "проверки и протокол."
        )
    )
    parser.add_argument(
        "--document",
        type=Path,
        default=DEFAULT_DOCUMENT,
        help=f"входной документ (по умолчанию {DEFAULT_DOCUMENT.name})",
    )
    parser.add_argument(
        "--package-name",
        default=DEFAULT_PACKAGE_NAME,
        help="имя пакета в реестре",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="адрес живого UI",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="таймаут ожидания прогона, секунды",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=None,
        help="путь к md-протоколу",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("cloud", "offline"),
        default="cloud",
        help="облачный LLM из .env или детерминированный offline",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="подтвердить destructive-очистку БД и outbox",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="не очищать БД (отладка; приёмка требует чистого старта)",
    )
    parser.add_argument(
        "--keep-running",
        action="store_true",
        help="оставить UI запущенным после прогона",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="проверить окружение и документ, ничего не менять",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="перезаписать существующий протокол",
    )
    return parser.parse_args(argv)


def dry_run(ctx: Acceptance) -> None:
    """Проверяет окружение и печатает план без изменений."""
    preflight(ctx)
    print("Документ:", ctx.document)
    print("SHA-256:", ctx.document_sha256)
    print("Коммит:", ctx.commit)
    print("LLM-режим:", ctx.args.llm_mode, "модель:", ctx.model)
    print("PostgreSQL: доступен")
    print("Neo4j: доступен")
    print("Протокол будет записан в:", ctx.protocol_path)
    print("DRY-RUN: изменения не выполнялись")


def execute(ctx: Acceptance) -> None:
    """Выполняет приёмочный сценарий целиком."""
    preflight(ctx)
    if not ctx.args.no_clean:
        clean(ctx)
    else:
        ctx.note("Очистка пропущена; пустое приложение может не подтвердиться")
    start(ctx)
    upload(ctx)
    first_run(ctx)
    review(ctx)
    rerun(ctx)
    report(ctx)
    graph(ctx)
    persistence(ctx)
    negative(ctx)


def main(argv: list[str] | None = None) -> int:
    """Полный приёмочный прогон на реальных PostgreSQL и Neo4j.

    Запуск: make acceptance CONFIRM=1 (или с флагом --confirm).
    Сценарий: очистка БД и outbox, запуск UI, загрузка demo/калькулятор.md,
    первый прогон, ревью фактов и пар, повторный анализ, проверка отчёта,
    графа и каркаса, рестарт UI с проверкой персистентности и негативные
    проверки формы приёма. Облачный LLM недетерминирован, поэтому протокол
    фиксирует фактические числа, а не ожидания offline-режима.
    """
    args = parse_args(argv)
    ctx = Acceptance(args)
    try:
        if args.dry_run:
            dry_run(ctx)
            return 0
        if not args.no_clean and not args.confirm:
            print(
                "Приёмочный прогон очищает PostgreSQL, Neo4j, outbox/ и logs/.\n"
                "Повторите с --confirm (или make acceptance CONFIRM=1)."
            )
            return 2
        execute(ctx)
        verdict = "PASS"
    except AcceptanceError as exc:
        ctx.error = str(exc)
        verdict = "FAIL"
        print(f"[FAIL] {exc}", flush=True)
    except Exception:  # noqa: BLE001 - протокол должен зафиксировать любую ошибку
        ctx.error = traceback.format_exc()
        verdict = "FAIL"
        print(ctx.error, flush=True)
    finally:
        if ctx.server is not None and not args.keep_running:
            ctx.server.stop()
        if ctx.http is not None:
            ctx.http.close()

    if ctx.checks or ctx.error:
        path = write_protocol(ctx, verdict)
        print(f"Протокол: {path}")
    else:
        path = None
    print(f"Итог: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
