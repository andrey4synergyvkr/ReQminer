from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from contracts.records import Package
from contracts.workflow import FileVerdict, PackageStatus
from services.common.formats import format_ts
from services.ingestor.scanner import ALLOWED_FORMATS


def prepare_package_dir(pkg_dir: Path) -> None:
    """Пустой каталог пакета в inbox (прежнее содержимое не подмешивается)."""
    if pkg_dir.exists():
        shutil.rmtree(pkg_dir)
    pkg_dir.mkdir(parents=True, exist_ok=True)


def build_package(
    pid: str,
    name: str,
    direction: str,
    staged: list[dict],
    ok_files: list[dict],
    rejected: list[dict],
    now: datetime,
) -> Package:
    """Строка реестра по результатам приёма - одна для обоих бэкендов."""
    reject_reason = None
    if not ok_files:
        if rejected and all(
            s.get("reject_reason") == "недопустимое имя файла" for s in rejected
        ):
            reject_reason = "недопустимое имя файла"
        elif rejected:
            reject_reason = "недопустимый формат"
        else:
            reject_reason = "файлы не выбраны"
    return {
        "id": pid,
        "name": name,
        "direction": direction,
        "documents": len(ok_files),
        "status": (PackageStatus.RUN.value if ok_files
                   else PackageStatus.REJECT.value),
        "facts": None,
        "last_run": format_ts(now),
        "started": now.isoformat(timespec="seconds"),
        "reject_reason": reject_reason,
        "files": staged,
    }


def _safe_name(raw: object) -> str | None:
    """Имя файла без выхода за каталог пакета; None - недопустимое."""
    name = str(raw or "").strip()
    if not name or name in {".", ".."}:
        return None
    if name != Path(name).name or "/" in name or "\\" in name:
        return None
    if Path(name).is_absolute() or (len(name) > 1 and name[1] == ":"):
        return None
    if any(ord(char) < 32 for char in name):
        return None
    return name


def prepare_staged(
    pkg_dir: Path, staged: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Пишет принятые файлы в inbox; возвращает (принятые, отклонённые).

    Имя файла - баррикада: абсолютные пути, `..`, разделители и
    управляющие символы отклоняются, запись идёт только внутрь pkg_dir.
    """
    ok_files: list[dict] = []
    rejected: list[dict] = []
    for item in staged:
        name = _safe_name(item.get("name"))
        if name is None:
            item["format"] = "недопустимый"
            item["verdict"] = FileVerdict.REJECT.value
            item["reject_reason"] = "недопустимое имя файла"
            item.pop("content", None)
            rejected.append(item)
            continue

        item["name"] = name
        ext = Path(name).suffix.lower()
        fmt = ALLOWED_FORMATS.get(ext)
        item["format"] = fmt or ext.lstrip(".")
        item["verdict"] = (
            FileVerdict.OK.value if fmt else FileVerdict.REJECT.value
        )
        if fmt:
            (pkg_dir / name).write_bytes(item.pop("content", b""))
            ok_files.append(item)
        else:
            item.pop("content", None)
            rejected.append(item)
    return ok_files, rejected
