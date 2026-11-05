from __future__ import annotations

from datetime import datetime

DISPLAY_TS_FORMAT = "%d.%m.%Y %H:%M"


def format_ts(value: datetime | None = None) -> str:
    """Дата и время для экранов и записей реестра."""
    return (value or datetime.now()).strftime(DISPLAY_TS_FORMAT)


def format_iso_ts(value: str) -> str:
    """ISO-время (started) в отображаемый формат; неразобранное - как есть."""
    try:
        return format_ts(datetime.fromisoformat(value))
    except (TypeError, ValueError):
        return value
