from __future__ import annotations

from datetime import datetime

from services.common.formats import format_iso_ts, format_ts


def test_format_ts_uses_single_format():
    assert format_ts(datetime(2026, 10, 31, 9, 5)) == "31.10.2026 09:05"


def test_format_iso_ts_parses_started():
    assert format_iso_ts("2026-10-31T09:05:00") == "31.10.2026 09:05"


def test_format_iso_ts_keeps_unparsed_value():
    assert format_iso_ts("") == ""
    assert format_iso_ts("не время") == "не время"
