from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import Field, Session, SQLModel, select

from contracts.records import Package, Run
from contracts.workflow import PackageStatus, RunState
from services.common.logging import get_logger
from services.orchestrator.staging import (
    build_package,
    prepare_package_dir,
    prepare_staged,
)

log = get_logger("orchestrator.registry_pg")

_DATA_DIR = Path(__file__).resolve().parent / "data"


class PackageRow(SQLModel, table=True):
    """Строка таблицы registry_packages."""
    __tablename__ = "registry_packages"

    seq: Optional[int] = Field(default=None, primary_key=True)
    id: str = Field(unique=True, index=True)
    name: str = ""
    direction: str = ""
    documents: int = 0
    status: str = PackageStatus.RUN.value
    facts: Optional[int] = None
    last_run: Optional[str] = None
    started: Optional[str] = None
    reject_reason: Optional[str] = None
    files: str = "[]"  # JSON-массив записей формы приёма

    def to_dict(self) -> Package:
        """Преобразует строку в доменный пакет."""
        return {
            "id": self.id,
            "name": self.name,
            "direction": self.direction,
            "documents": self.documents,
            "status": self.status,
            "facts": self.facts,
            "last_run": self.last_run,
            "started": self.started,
            "reject_reason": self.reject_reason,
            "files": json.loads(self.files),
        }


class RunRow(SQLModel, table=True):
    """Строка таблицы registry_runs."""
    __tablename__ = "registry_runs"

    package: str = Field(primary_key=True)
    state: str = RunState.RUN.value
    started: Optional[str] = None
    finished: Optional[str] = None
    stages: str = "[]"  # JSON-массив этапов конвейера
    metrics: str = "{}"  # JSON-объект метрик прогона
    progress: str = "{}"  # JSON-объект прогресса (ProgressReporter)
    error: Optional[str] = None

    def to_dict(self) -> Run:
        """Преобразует строку в доменный прогон."""
        run = {
            "state": self.state,
            "started": self.started,
            "stages": json.loads(self.stages),
            "metrics": json.loads(self.metrics),
            "finished": self.finished,
        }
        progress = json.loads(self.progress or "{}")
        if progress:
            run["progress"] = progress
        if self.error:
            run["error"] = self.error
        return run


class SqlRegistry:
    """Реестр пакетов и прогонов на PostgreSQL: те же функции, что in-memory.

    Пакеты лежат в registry_packages, прогоны - в registry_runs. Списки
    читаются по убыванию seq, поэтому новые пакеты идут первыми; номер
    пакета берётся из БД и переживает рестарт процесса.
    """

    def __init__(self, inbox_root: Path) -> None:
        self._inbox_root = inbox_root

    def _session(self) -> Session:
        # engine гарантированно не None: бэкенд создается только при успехе
        # подключения (db.init_db в registry.py)
        from services.common.db import get_engine

        return Session(get_engine())

    # --- сиды ------------------------------------------------------------------
    def load_seeds(self) -> None:
        """Загружает сиды контрольного примера, если таблицы пусты."""
        with self._session() as session:
            if session.exec(select(PackageRow).limit(1)).first() is None:
                with open(_DATA_DIR / "packages.json", encoding="utf-8") as f:
                    for pkg in json.load(f):
                        session.add(PackageRow(
                            id=pkg["id"],
                            name=pkg["name"],
                            direction=pkg["direction"],
                            documents=pkg["documents"],
                            status=pkg["status"],
                            facts=pkg["facts"],
                            last_run=pkg["last_run"],
                            started=pkg.get("started"),
                            reject_reason=pkg.get("reject_reason"),
                            files=json.dumps(pkg.get("files", []), ensure_ascii=False),
                        ))
                session.commit()

            if session.exec(select(RunRow).limit(1)).first() is None:
                with open(_DATA_DIR / "runs.json", encoding="utf-8") as f:
                    runs: dict[str, dict] = json.load(f)
                for pid, run in runs.items():
                    session.add(RunRow(
                        package=pid,
                        state=run["state"],
                        started=run.get("started"),
                        finished=run.get("finished"),
                        stages=json.dumps(run.get("stages", []), ensure_ascii=False),
                        metrics=json.dumps(run.get("metrics", {}), ensure_ascii=False),
                        error=run.get("error") or run.get("reason"),
                    ))
                session.commit()

    # --- API реестра -----------------------------------------------------------
    def inbox_dir(self, package: str) -> Path:
        """Каталог пакета во входящих."""
        return self._inbox_root / package

    def list_packages(self) -> list[Package]:
        """Все пакеты реестра."""
        with self._session() as session:
            rows = session.exec(
                select(PackageRow).order_by(PackageRow.seq.desc())
            ).all()
        return [r.to_dict() for r in rows]

    def get_package(self, pid: str) -> Package | None:
        """Пакет по id или None."""
        with self._session() as session:
            row = session.exec(
                select(PackageRow).where(PackageRow.id == pid)
            ).first()
        return row.to_dict() if row else None

    def update_package(self, pid: str, **fields) -> None:
        """Обновляет поля пакета."""
        with self._session() as session:
            row = session.exec(
                select(PackageRow).where(PackageRow.id == pid)
            ).first()
            if row is None:
                return
            for key, value in fields.items():
                if key == "files":
                    row.files = json.dumps(value, ensure_ascii=False)
                else:
                    setattr(row, key, value)
            session.add(row)
            session.commit()

    def get_run(self, pid: str) -> Run | None:
        """Прогон пакета или None."""
        with self._session() as session:
            row = session.exec(
                select(RunRow).where(RunRow.package == pid)
            ).first()
        return row.to_dict() if row else None

    def set_run(self, pid: str, run: Run) -> None:
        """Сохраняет прогон пакета."""
        with self._session() as session:
            row = session.exec(
                select(RunRow).where(RunRow.package == pid)
            ).first()
            if row is None:
                row = RunRow(package=pid)
            row.state = run["state"]
            row.started = run["started"]
            row.finished = run["finished"]
            row.stages = json.dumps(run["stages"], ensure_ascii=False)
            row.metrics = json.dumps(run["metrics"], ensure_ascii=False)
            row.progress = json.dumps(run.get("progress") or {}, ensure_ascii=False)
            row.error = run.get("error")
            session.add(row)
            session.commit()

    def create_package(self, name: str, direction: str, staged: list[dict],
                       pid: str | None = None) -> Package:
        """Регистрирует пакет по данным формы приёма (как in-memory).

        pid задается только тестами-сидами; очередной номер берется
        из БД и переживает рестарт процесса. Коллизия номера (второй
        инстанс) обрабатывается повтором с новым номером.
        """
        from sqlalchemy.exc import IntegrityError

        requested_pid = pid
        items = [dict(item) for item in staged]  # content нужен для повтора
        for attempt in range(3):
            if requested_pid is not None:
                pid = requested_pid
            with self._session() as session:
                if pid is None:
                    numbers = [
                        int(p.id.rsplit("-", 1)[1])
                        for p in session.exec(select(PackageRow)).all()
                        if len(p.id.rsplit("-", 1)) == 2
                        and p.id.rsplit("-", 1)[1].isdigit()
                    ]
                    pid = f"2026-{max(numbers, default=42) + 1:03d}"
                now = datetime.now()

                pkg_dir = self._inbox_root / pid
                prepare_package_dir(pkg_dir)
                current = [dict(item) for item in items]
                ok_files, rejected = prepare_staged(pkg_dir, current)
                fields = build_package(pid, name, direction, current,
                                       ok_files, rejected, now)
                row = PackageRow(
                    id=fields["id"],
                    name=fields["name"],
                    direction=fields["direction"],
                    documents=fields["documents"],
                    status=fields["status"],
                    facts=None,
                    last_run=fields["last_run"],
                    started=fields["started"],
                    reject_reason=fields["reject_reason"],
                    files=json.dumps(fields["files"], ensure_ascii=False),
                )
                session.add(row)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    if requested_pid is not None or attempt == 2:
                        raise
                    pid = None
                    continue
                session.refresh(row)
                break
        if row.status == PackageStatus.REJECT:
            log.warning("Пакет %s отклонен: %s", pid, fields["reject_reason"])
        else:
            log.info(
                "Пакет %s принят: «%s», документов %d, карантин %d",
                pid, name, len(ok_files), len(rejected),
            )
        return row.to_dict()

    def reset(self, package: str | None = None) -> None:
        """Очистка (тесты); без аргумента - весь реестр."""
        from sqlmodel import delete

        with self._session() as session:
            if package is None:
                session.exec(delete(PackageRow))
                session.exec(delete(RunRow))
            else:
                session.exec(delete(PackageRow).where(PackageRow.id == package))
                session.exec(delete(RunRow).where(RunRow.package == package))
            session.commit()
