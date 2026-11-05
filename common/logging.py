from __future__ import annotations

import logging
import sys
from pathlib import Path

from services.common import settings

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FILE = LOG_DIR / "reqminer.log"

_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_configured = False


def configure(level: str | None = None) -> None:
    """Настраивает журналирование: консоль и файл logs/reqminer.log.

    Файл открывается в режиме append без ротации: несколько процессов
    пишут в один журнал, а переименование занятого файла на Windows падает.
    """
    global _configured
    if _configured:
        return
    _configured = True

    console_level = (level or settings.log_level()).upper()
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(formatter)

    LOG_DIR.mkdir(exist_ok=True)
    logfile = logging.FileHandler(LOG_FILE, encoding="utf-8")
    logfile.setLevel(logging.DEBUG)
    logfile.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(logfile)

    # болтливые библиотеки: их DEBUG-потоки не проходят в файл
    for noisy in ("neo4j", "httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Логгер сервиса: get_logger("ingestor.scanner")."""
    return logging.getLogger(name)
