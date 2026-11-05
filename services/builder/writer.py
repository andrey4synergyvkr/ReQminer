from __future__ import annotations

import io
import zipfile
from pathlib import Path

from services.common import settings


def _root() -> Path:
    """Корень outbox (env OUTBOX_ROOT, по умолчанию - outbox/ в корне проекта)."""
    return settings.outbox_root()


def write(package: str, docs: dict[str, str]) -> Path:
    """Записывает файлы каркаса пакета; существующие файлы перезаписываются."""
    root = _root() / package
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in docs.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def read(package: str, rel_path: str) -> str | None:
    """Читает файл каркаса; rel_path ограничен корнем outbox пакета."""
    root = (_root() / package).resolve()
    target = (root / rel_path).resolve()
    # защита от выхода за корень outbox (path traversal)
    if root not in target.parents and target != root:
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def zip_package(package: str) -> bytes:
    """Экспорт каркаса пакета в zip (в памяти)."""
    root = _root() / package
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buf.getvalue()
